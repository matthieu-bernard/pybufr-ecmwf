#!/usr/bin/env python

"""
This file defines the RawBUFRFile class, an alternative for
loading and writing the binary raw BUFR messages from and to file
(needed because I cannot get the interface to the pb routines defined
in the ECMWF BUFR library to work in a portable way)
"""

#  #[ documentation
#
# Note about the use of the "#  #[" and "#  #]" comments:
#   these are folding marks for my favorite editor, emacs, combined with its
#   folding mode
#   (see http://www.emacswiki.org/emacs/FoldingMode for more details)
# Please do not remove them.
#
# For details on the revision history, refer to the log-notes in
# the mercurial revisioning system hosted at google code.
#
# Written by: J. de Kloe, KNMI (www.knmi.nl), Initial version 12-Nov-2009    
#
# License: GPL v2.
#
#  #]
#  #[ imported modules
import os          # operating system functions
import numpy as np # import numerical capabilities
import struct      # allow converting c datatypes and structs

#  #]

class RawBUFRFile:
    #  #[
    """
    a class to read and write the binary BUFR messages from and
    to file. Is is intended to replace the pbio routines from the ECMWF
    library which for some obscure reason cannot be interfaced
    easily to python using the f2py tool.
    """
    def __init__(self, verbose = False):
        #  #[
        self.bufr_fd  = None
        self.filename = None
        self.filemode = None
        self.filesize = None
        self.data     = None
        self.list_of_bufr_pointers = []
        self.nr_of_bufr_messages = 0
        self.last_used_msg = 0
        self.verbose = verbose
        #  #]
    def print_properties(self, prefix = "BUFRFile"):
        #  #[
        """
        print the properties of the current RawBUFRFile instance
        """
        # this one causes trouble with the unittesting since it gives
        # different addresses each time, and is not so very interesting
        # to print, so leave it out for now
        #print prefix+": bufr_fd  = ", self.bufr_fd
        print prefix+": filename = ", self.filename
        print prefix+": filemode = ", self.filemode
        print prefix+": filesize = ", self.filesize
        if (self.data != None):
            print prefix+": len(data) = ", len(self.data)
        else:
            print prefix+": data = ", self.data
        print prefix+": list_of_bufr_pointers = ", \
              self.list_of_bufr_pointers
        print prefix+": nr_of_bufr_messages = ", self.nr_of_bufr_messages
        #print prefix+":  = ", self.
        #  #]
    def open(self, filename, mode, silent = False):
        #  #[
        """
        open a BUFR file to allow reading or writing raw BUFR messages
        """
        # note: the silent switch is only intended to suppress
        # warning and error messages during unit testing.
        # During normal use it should never be set to True.
        
        self.filename = filename
        self.filemode = mode
        
        # filename should include the path specification as well
        assert(mode in ['r', 'w', 'a'])

        if (mode == 'r'):
            if (os.path.exists(filename)):
                self.filesize = os.path.getsize(filename)
            else:
                if (not silent):
                    print "ERROR in BUFRFile.open():"
                    print "Opening file: ", self.filename, " with mode: ", \
                          self.filemode, " failed"
                    print "This file was not found or is not accessible."
                raise IOError
        elif (mode == 'w'):
            self.filesize = 0
        elif (mode == 'a'):
            # when appending it is allowed to have a non-existing
            # file, in which case one will be generated, so test for
            # this condition
            if (os.path.exists(filename)):
                # in this case, try to find out the amount of BUFR messages
                # already present in this file, by temporary opening
                # it in reading mode
                tmp_bf = RawBUFRFile()
                tmp_bf.open(filename, 'r')
                #tmp_bf.print_properties(prefix = "tmp_bf (opened for reading)")
                count = tmp_bf.get_num_bufr_msgs()
                tmp_bf.close()
                del(tmp_bf)

                # then store the found number for later use
                self.nr_of_bufr_messages = count
                self.filesize = os.path.getsize(filename)

                if ((count == 0) and (self.filesize>0)):
                    print "WARNING: appending to non-zero file, but could"
                    print "not find any BUFR messages in it. Maybe you are"
                    print "appending to a non-BUFR file??"
            else:
                self.filesize = 0            

        try:
            self.bufr_fd = open(filename, mode)
        except:
            if (not silent):
                print "ERROR in BUFRFile.open():"
                print "Opening file: ", self.filename, " with mode: ", \
                      self.filemode, " failed"
            raise IOError

        if (mode == 'r'):
            try:
                self.data = self.bufr_fd.read()
            except:
                if (not silent):
                    print "ERROR in BUFRFile.open():"
                    print "Reading data from file: ", self.filename, \
                          " with mode: ", self.filemode, " failed"
                raise IOError

            # split in separate BUFR messages
            self.split()

        #  #]
    def close(self):
        #  #[
        """
        close a BUFR file
        """
        # close the file
        self.bufr_fd.close()
        # then erase all settings
        self.__init__()
        #  #]
    def get_expected_msg_size(self, start_location):
        #  #[
        """ a routine to extract the expected message size from
        a BUFR message, needed to verify which start tag BUFR matches
        which end tag 7777. It also helps in excluding corrupted
        and falsely identified messages.
        """
        # According to ECMWF's BUFR User Guide:
        # http://www.ecmwf.int/products/data/software/bufr_user_guide.pdf
        # the first 8 bytes of a BUFR message should contain:
        # 1-4 : the four letters BUFR
        # 5-7 : total length of BUFR msg in bytes
        # 8   : BUFR Edition number (newest one currently is 4)
        #       valid edition numbers are 0,1,2,3,4
        # However, the oldest edition numbers 0 and 1 are exceptions
        # they do not have the full message lenght in section0, and in
        # fact only have a 4 byte section 0.
        # See the WMO BUFR Guide
        # http://www.wmo.int/pages/prog/www/WMOCodes/...
        #        Guides/BUFRCREX/Layer3-English-only.pdf
        # which is available from:
        # http://www.wmo.int/pages/prog/www/WMOCodes/...
        #        Guides/BUFRCREXPreface_en.html
        # Luckily the fourth byte of section 1 still gives the edition
        # number for these cases (although in later editions this byte
        # indicates the Bufr master Table version)
        # For these editions it is needed to retrieve the sections lenghts by
        # scanning each of the 6 sections and add them manually ...
        
        # Note: I hope to never see cray-blocked files again in my life
        # so this routine will not properly handle these ...
        # (these types of BUFR files do not conform to the BUFR
        #  standard anyway, so nobody should use them, but they might
        #  pop-up now and then from some old archive)
        # If you need to use this kind of files, write your own correction
        # routine to remove the 8 byte control-words inserted at every
        # 4096 bytes by this weird fileformat before trying to use them.
        
        if (self.verbose):
            print 'getting message size of start location: ', start_location
        try:
            raw_edition_number = self.data[start_location+8-1]
            edition_number = ord(raw_edition_number)
            if (self.verbose):
                print 'edition_number = ', edition_number
        except IndexError:
             # 0 signals this is not a valid BUFR msg, might be a false
             # start BUFR string, or a corrupted or truncated file
            return 0

        # note: the headers seem to use big-endian encoding
        # even on little endian machines, for the msg size.
        dataformat = ">1i"

        try:
            if edition_number > 1:
                # get bytes 5 to 7 which should hold the total length of the
                # current BUFR message
                raw_bytes = chr(0)+self.data[start_location+5-1:
                                             start_location+7]
                msg_size = struct.unpack(dataformat, raw_bytes)[0]
            else:
                size_section0 = 4

                # retrieve size of section 1
                offset = size_section0
                # get length of section 1 from bytes 1 to 3
                raw_bytes = chr(0)+self.data[start_location+offset+1-1:
                                             start_location+offset+3]
                size_section1 = struct.unpack(dataformat, raw_bytes)[0]

                # see if the optional section 2 is present or not
                # this is indicated by bit 1 of byte 8 of section 1
                byte8 = ord(self.data[start_location+offset+8-1])
                section2_present = False
                if (byte8 & 1):
                    section2_present = True
                
                if section2_present:
                    # retrieve size of section 2
                    offset = size_section0 + size_section1
                    # get length of section 2 from bytes 1 to 3
                    raw_bytes = chr(0)+self.data[start_location+offset+1-1:
                                                 start_location+offset+3]
                    size_section2 = struct.unpack(dataformat, raw_bytes)[0]
                else:
                    size_section2 = 0
                    
                # retrieve size of section 3
                offset = size_section0 + size_section1 + size_section2
                # get length of section 3 from bytes 1 to 3
                raw_bytes = chr(0)+self.data[start_location+offset+1-1:
                                             start_location+offset+3]
                size_section3 = struct.unpack(dataformat, raw_bytes)[0]

                # retrieve size of section 4
                offset = size_section0 + size_section1 + \
                         size_section2 + size_section3
                # get length of section 4 from bytes 1 to 3
                raw_bytes = chr(0)+self.data[start_location+offset+1-1:
                                             start_location+offset+3]
                size_section4 = struct.unpack(dataformat, raw_bytes)[0]

                size_section5 = 4

                # print 'size section 0 = ',size_section0
                # print 'size section 1 = ',size_section1
                # print 'size section 2 = ',size_section2
                # print 'size section 3 = ',size_section3
                # print 'size section 4 = ',size_section4
                # print 'size section 5 = ',size_section5

                msg_size = size_section0 + size_section1 + \
                           size_section2 + size_section3 + \
                           size_section4 + size_section5

        except IndexError:
             # 0 signals this is not a valid BUFR msg, might be a false
             # start BUFR string, or a corrupted or truncated file
            return 0

        # see: p.L3-3 (p.5) of the file Layer3-English-only.pdf
        #      mentioned above.
        if msg_size > 15000:
            print "WARNING: by convention BUFR messages should not be larger"
            print "         than 15kb to allow transmission over the GTS."
            print "         Size of current message is: ", msg_size, " bytes"

        return msg_size
        #  #]        
    def split(self):
        #  #[
        """
        scan a BUFR file to detect the start and end locations of the
        separate BUFR messages. Note that a BUFR file may contain
        additional junk, like GTS headers and such. The code should be
        robust enough to handle this.
        """
        # Purpose: scans the file for the string "BUFR"
        # which indicate the start of a new BUFR message,
        # counts the nr of BUFR messages, and stores file
        # pointers to the start of each BUFR message.

        # safety catch
        if (self.filesize == 0):
            self.nr_of_bufr_messages = 0
            return

        # note: this very simpple search algorithm might accidently
        # find the string "7777" in the middle of the data of a BUFR message.
        # To check on this, make sure the distance between the end of a
        # message and the start of a message if either 0 or 2 bytes
        # (this may happen if the file is padded with zeros to contain
        #  a multiple of 4 bytes)
        # Do the same check on the end of the file.

        txt_start  = "BUFR"
        txt_end    = "7777"
        list_of_start_locations = []
        list_of_end_locations   = []

        # try to find the start strings
        search_pos = 0
        file_end_reached = False
        while not file_end_reached:
            start_pos = self.data.find(txt_start, search_pos)
            if (start_pos == -1):
                file_end_reached = True
            else:
                list_of_start_locations.append(start_pos)
                search_pos = start_pos + 4

        # try to find the end strings
        search_pos = 0
        file_end_reached = False
        while not file_end_reached:
            end_pos = self.data.find(txt_end, search_pos)
            if (end_pos == -1):
                file_end_reached = True
            else:
                list_of_end_locations.append(end_pos)
                search_pos = end_pos + 4

        self.list_of_bufr_pointers = []

        # try each BUFR message; extract its length and see if
        # it matches an end location. If not we found a false start
        # marker or a corrupt BUFR message. If it matches, assume
        # the BUFR message is valid and add it to the list
        for start_location in list_of_start_locations:
            expected_msg_size = self.get_expected_msg_size(start_location)
            if (self.verbose):
                print 'expected_msg_size = ', expected_msg_size
            expected_msg_end_location = start_location + expected_msg_size - 4
            if expected_msg_end_location in list_of_end_locations:
                if (self.verbose):
                    print 'message seems alright, adding it to the list'
                # point to the end of the four sevens
                # (in slice notation, so the bufr msg data
                # can be adressed as data[start_pos:end_pos])
                # and store it
                self.list_of_bufr_pointers.append((start_location,
                                                   expected_msg_end_location+4))
        

        # count howmany we found
        self.nr_of_bufr_messages = len(self.list_of_bufr_pointers)

        if (self.verbose):
            print "list_of_start_locations = ", list_of_start_locations
            print "list_of_end_locations   = ", list_of_end_locations

        #  #]
    def split_simple(self):
        #  #[
        """
        scan a BUFR file to detect the start and end locations of the
        separate BUFR messages. Note that a BUFR file may contain
        additional junk, like GTS headers and such. The code should be
        robust enough to handle this.
        """
        # NOTE: the assumption made here that BUFR messages are glued
        # together without gaps is not always true!
        # Especially data coming from GTS systems often have GTS-headers
        # attached in front of each individual BUFR message (and this
        # is allowed, so the newer split routine defined above was
        # added to handle this)
        
        # Purpose: scans the file for the string "BUFR"
        # which indicate the start of a new BUFR message,
        # counts the nr of BUFR messages, and stores file
        # pointers to the start of each BUFR message.

        # safety catch
        if (self.filesize == 0):
            self.nr_of_bufr_messages = 0
            return

        # note: this very simpple search algorithm might accidently
        # find the string "7777" in the middle of the data of a BUFR message.
        # To check on this, make sure the distance between the end of a
        # message and the start of a message if either 0 or 2 bytes
        # (this may happen if the file is padded with zeros to contain
        #  a multiple of 4 bytes)
        # Do the same check on the end of the file.

        inside_message   = False
        file_end_reached = False
        search_pos = 0
        start_pos  = -1
        end_pos    = -1
        txt_start  = "BUFR"
        txt_end    = "7777"
        while not file_end_reached:

            if (not inside_message):
                # try to find a txt_start string
                start_pos = self.data.find(txt_start, search_pos)
                if (self.verbose):
                    print "search_pos = ", search_pos, \
                          " start_pos = ", start_pos, \
                          " txt = ", txt_start

                if (start_pos != -1):
                    inside_message = True

                    # sanity check, see if distance to the previous BUFR
                    # message is no more than 4 bytes
                    if (end_pos != -1):
                        distance = (start_pos-end_pos)
                        if (self.verbose):
                            print "distance = ", distance, " bytes"
                        if (distance > 3):
                            # this means we have found a false "7777"
                            # end marker, so ignore the last added msg
                            # and start looking again
                            prev_start_pos = \
                                           self.list_of_bufr_pointers.pop()[0]
                            # restore the previous msg start pos
                            # to allow trying to search again for a correct
                            # end marker
                            start_pos = prev_start_pos
                            if (self.verbose):
                                print "restored start_pos = ", start_pos

                            # step over the "7777" string to prepare for
                            #  searching the real end of the message
                            search_pos = end_pos
                        else:
                            # step over the "BUFR" string to prepare for
                            #  searching the end of the message
                            search_pos = start_pos+4


                else:
                    # check the distance to the fileend
                    # This should be no more than 4 bytes.
                    # If it is larger we have found a false "7777"
                    # end marker (or the file is corrupted and truncated)
                    distance = (self.filesize-end_pos)
                    if (self.verbose):
                        print "distance to fileend = ", distance, " bytes"
                    if (distance > 3):
                        # this means we have found a false "7777"
                        # end marker, so ignore the last added msg
                        # and start looking again
                        prev_start_pos = \
                                       self.list_of_bufr_pointers.pop()[0]
                        # restore the previous msg start pos
                        # to allow trying to search again for a correct
                        # end marker
                        start_pos = prev_start_pos
                        if (self.verbose):
                            print "restored start_pos = ", start_pos
                        
                        # step over the "7777" string to prepare for
                        #  searching the real end of the message
                        search_pos = end_pos

                        # file end was not yet reached, keep on looking
                        file_end_reached = False
                        inside_message = True
                    else:
                        # file end was not really reached
                        file_end_reached = True

                    
            if (inside_message and not file_end_reached):
                # try to find a txt_end string
                end_pos = self.data.find(txt_end, search_pos)
                if (self.verbose):
                    print "search_pos = ", search_pos, \
                          " end_pos = ", end_pos, \
                          " txt = ", txt_end

                if (end_pos != -1):
                    inside_message = False

                    # point to the end of the four sevens
                    # (in slice notation, so the bufr msg data
                    # can be adressed as data[start_pos:end_pos])
                    end_pos = end_pos+4
                    
                    # step over the "7777" string to prepare for searching the
                    # end start of the next message
                    search_pos = end_pos

                    # store the found message
                    self.list_of_bufr_pointers.append((start_pos, end_pos))
                else:
                    file_end_reached = True

        # count howmany we found
        self.nr_of_bufr_messages = len(self.list_of_bufr_pointers)
        #  #]
    def get_num_bufr_msgs(self):
        #  #[
        """
        request the number of BUFR messages in the current file
        """
        if (self.bufr_fd == None):
            print "ERROR: a bufr file first needs to be opened"
            print "using BUFRFile.open() before you can request the"
            print "number of BUFR messages in a file .."
            raise IOError

        return self.nr_of_bufr_messages
        #  #]
    def get_raw_bufr_msg(self, msg_nr):
        #  #[
        """
        get the raw data for the BUFR message with given msg_nr
        (start counting at 1)
        """
        
        if (self.bufr_fd == None):
            print "ERROR: a bufr file first needs to be opened"
            print "using BUFRFile.open() before you can use the raw data .."
            raise IOError

        # sanity test
        if (msg_nr>self.nr_of_bufr_messages):
            print "WARNING: non-existing BUFR message: ", msg_nr
            print "This file only contains: ", self.nr_of_bufr_messages, \
                  " BUFR messages"
            return None

        if (msg_nr<1):
            print "WARNING: invalid BUFR message number: ", msg_nr
            print "For this file this number should be between 1 and: ", \
                  self.nr_of_bufr_messages
            return None

        self.last_used_msg = msg_nr
        (start_index, end_index) = self.list_of_bufr_pointers[msg_nr-1]

        size_bytes = (end_index-start_index)

        # +3 because we have to round upwards to make sure all
        # bytes fit into the array of words (otherwise the last
        # few might be truncated from the data, which will crash
        # the struct.unpack() call below)
        size_words = (size_bytes+3)/4
        padding_bytes = size_words*4-size_bytes

        if (self.verbose):
            print "size_bytes = ", size_bytes
            print "size_words = ", size_words
            print "size_words*4 = ", size_words*4
            print "padding_bytes = ", padding_bytes
            
        # make sure we take the padding bytes along
        end_index = end_index+padding_bytes
        
        raw_data_bytes = self.data[start_index:end_index]
        if (self.verbose):
            print "len(raw_data_bytes) = ", len(raw_data_bytes)

        # assume little endian for now when converting
        # raw bytes/characters to integers and vice-versa
        dataformat = "<"+str(size_words)+"i"
        words = np.array(struct.unpack(dataformat, raw_data_bytes))

        return words
        #  #]
    def get_next_raw_bufr_msg(self):
        #  #[
        """
        get the raw data for the next BUFR message.
        This routine uses the internal instance variable last_used_msg
        to store the index of the last read BUFR message.
        """
        return self.get_raw_bufr_msg(self.last_used_msg+1)
        #  #]
    def write_raw_bufr_msg(self, words):
        #  #[
        """
        write the raw BUFR message data to the BUFR file
        """
        # input data should be an array of words!
        size_words = len(words)
        size_bytes = size_words*4
        if (self.verbose):
            print "size_bytes = ", size_bytes
            print "size_words = ", size_words

        # convert the words to bytes in a string and write them to file

        # question: is this conversion really needed, or could I also just
        # directly write the data as words?
        # Answer: yes this really is needed! If the words are just written
        # as such, python converts them to long integers and writes
        # 8 bytes for each word in stead of 4 !!!!!
        # activate the next 2 lines to test this:
        #self.bufr_fd.write(words)
        #return
        
        # assume little endian for now when converting
        # raw bytes/characters to integers and vice-versa
        dataformat = "<i"
        for (i, word) in enumerate(words):
            data = struct.pack(dataformat, word)
            self.bufr_fd.write(data)

            if i == 0:
                if (self.verbose):
                    print "word = ", word
                    print 'data = ', data
                    print 'data[:4] = ', data[:4]
                    print 'data[:4] = ', ';'.join(str(data[j])
                                                 for j in range(4) \
                                                 if data[j].isalnum())
                # safety check
                assert(data[:4] == 'BUFR')

        self.nr_of_bufr_messages = self.nr_of_bufr_messages + 1
        self.filesize = self.filesize + size_bytes
        #  #]
    #  #]
