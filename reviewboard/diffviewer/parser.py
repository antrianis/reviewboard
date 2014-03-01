import logging
import re


class File(object):
    def __init__(self):
        self.origFile = None
        self.newFile = None
        self.origInfo = None
        self.newInfo = None
        self.origChangesetId = None
        self.data = None
        self.binary = False
        self.deleted = False
        self.moved = False
        self.copied = False


class DiffParserError(Exception):
    def __init__(self, msg, linenum):
        Exception.__init__(self, msg)
        self.linenum = linenum


class DiffParser(object):
    """
    Parses diff files into fragments, taking into account special fields
    present in certain types of diffs.
    """

    INDEX_SEP = "=" * 67

    def __init__(self, data):
        self.data = data
        self.lines = data.splitlines()

    def parse(self):
        """
        Parses the diff, returning a list of File objects representing each
        file in the diff.
        """
        logging.debug("DiffParser.parse: Beginning parse of diff, size = %s",
                      len(self.data))

        preamble = ''
        self.files = []
        file = None
        i = 0

        # Go through each line in the diff, looking for diff headers.
        while i < len(self.lines):
            next_linenum, new_file = self.parse_change_header(i)

            if new_file:
                # This line is the start of a new file diff.
                file = new_file
                file.data = preamble + file.data
                preamble = ''
                self.files.append(file)
                i = next_linenum
            else:
                line = self.lines[i] + '\n'

                if file:
                    file.data += line
                else:
                    preamble += line

                i += 1

        logging.debug("DiffParser.parse: Finished parsing diff.")

        return self.files

    def parse_change_header(self, linenum):
        """
        Parses part of the diff beginning at the specified line number, trying
        to find a diff header.
        """
        info = {}
        file = None
        start = linenum
        linenum = self.parse_special_header(linenum, info)
        linenum = self.parse_diff_header(linenum, info)

        if info.get('skip', False):
            return linenum, None

        # If we have enough information to represent a header, build the
        # file to return.
        if ('origFile' in info and 'newFile' in info and
            'origInfo' in info and 'newInfo' in info):
            if linenum < len(self.lines):
                linenum = self.parse_after_headers(linenum, info)

                if info.get('skip', False):
                    return linenum, None

            file = File()
            file.binary   = info.get('binary', False)
            file.deleted  = info.get('deleted', False)
            file.moved    = info.get('moved', False)
            file.copied   = info.get('copied', False)
            file.origFile = info.get('origFile')
            file.newFile  = info.get('newFile')
            file.origInfo = info.get('origInfo')
            file.newInfo  = info.get('newInfo')
            file.origChangesetId = info.get('origChangesetId')

            # The header is part of the diff, so make sure it gets in the
            # diff content.
            file.data = ''.join([
                self.lines[i] + '\n' for i in xrange(start, linenum)
            ])

        return linenum, file

    def parse_special_header(self, linenum, info):
        """
        Parses part of a diff beginning at the specified line number, trying
        to find a special diff header. This usually occurs before the standard
        diff header.

        The line number returned is the line after the special header,
        which can be multiple lines long.
        """
        if linenum + 1 < len(self.lines) and \
           self.lines[linenum].startswith("Index: ") and \
           self.lines[linenum + 1] == self.INDEX_SEP:
            # This is an Index: header, which is common in CVS and Subversion,
            # amongst other systems.
            try:
                info['index'] = self.lines[linenum].split(None, 2)[1]
            except ValueError:
                raise DiffParserError("Malformed Index line", linenum)
            linenum += 2

        return linenum

    def parse_diff_header(self, linenum, info):
        """
        Parses part of a diff beginning at the specified line number, trying
        to find a standard diff header.

        The line number returned is the line after the special header,
        which can be multiple lines long.
        """
        if linenum + 1 < len(self.lines) and \
           ((self.lines[linenum].startswith('--- ') and
             self.lines[linenum + 1].startswith('+++ ')) or
            (self.lines[linenum].startswith('*** ') and
             self.lines[linenum + 1].startswith('--- ') and
             not self.lines[linenum].endswith(" ****"))):
            # This is a unified or context diff header. Parse the
            # file and extra info.
            try:
                info['origFile'], info['origInfo'] = \
                    self.parse_filename_header(self.lines[linenum][4:],
                                               linenum)
                linenum += 1

                info['newFile'], info['newInfo'] = \
                    self.parse_filename_header(self.lines[linenum][4:],
                                               linenum)
                linenum += 1
            except ValueError:
                raise DiffParserError("The diff file is missing revision " +
                                      "information", linenum)

        return linenum

    def parse_after_headers(self, linenum, info):
        """Parses data after the diff headers but before the data.

        By default, this does nothing, but a DiffParser subclass can
        override to look for special headers before the content.
        """
        return linenum

    def parse_filename_header(self, s, linenum):
        if "\t" in s:
            # There's a \t separating the filename and info. This is the
            # best case scenario, since it allows for filenames with spaces
            # without much work.
            return s.split("\t", 1)

        # There's spaces being used to separate the filename and info.
        # This is technically wrong, so all we can do is assume that
        # 1) the filename won't have multiple consecutive spaces, and
        # 2) there's at least 2 spaces separating the filename and info.
        if "  " in s:
            return re.split(r"  +", s, 1)

        raise DiffParserError("No valid separator after the filename was " +
                              "found in the diff header",
                              linenum)

    def raw_diff(self, diffset):
        """Returns a raw diff as a string.

        The returned diff as composed of all FileDiffs in the provided diffset.
        """
        return ''.join([filediff.diff for filediff in diffset.files.all()])

    def get_orig_commit_id(self):
        """Returns the commit ID of the original revision for the diff.

        This is overridden by tools that only use commit IDs, not file
        revision IDs.
        """
        return None
