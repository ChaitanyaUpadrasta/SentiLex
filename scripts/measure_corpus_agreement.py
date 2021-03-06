#!/usr/bin/env python2.7
# -*- coding: utf-8-unix; mode: python; -*-

"""
DESCRIPTION:
============
Script for measuring the inter-annotator agreement on MMAX corpus.

USAGE:
======
measure_corpus_agreement.py [OPTIONS] basedata_dir markables_dir1 markables_dir2

EXAMPLE:
========
(envoke from the top directory of the archive)
./scripts/measure_corpus_agreement.py --pattern='*.xml' corpus/basedata/ \
corpus/annotator-1/markables/ corpus/annotator-2/markables/

LICENSE:
========
Copyright (c) 2014-2015, ANONYMOUS
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
this list of conditions and the following disclaimer in the documentation
and/or other materials provided with the distribution.

* Neither the names of the authors nor the names of its contributors may be
used to endorse or promote products derived from this software without specific
prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""

##################################################################
# Libararies
from merge_conll_mmax import parse_span

from collections import deque
from copy import copy, deepcopy

import argparse
import glob
import os
import re
import sys
import string
import xml.etree.ElementTree as _ET

##################################################################
# Variables and Constants
MATCH_MRKBL_IDX = 0
TOTAL_MRKBL_IDX = 1

OFFSET_IDX = 0

OVERLAP1_IDX = 0
TOTAL1_IDX = 1
OVERLAP2_IDX = 2
TOTAL2_IDX = 3

MISSING = "missing"
REDUNDANT = "redundant"
MARKABLE = "markable"

WRD_PRFX = "word_"
WRD_PRFX_RE = re.compile("word_")
WRD_SEP = ","
WRD_RANGE_SEP = ".."

NAMESPACE_PRFX = "www.eml.org/NameSpaces/"

DIFF_PRFX = "diff-"
BASEDATA_SFX = ".words.xml"
SMILEY_RE = re.compile(r"(?:ha|d|x|lol|" + '|'.join([re.escape(c) for c in string.punctuation]) + ")+$", \
                           re.I)
MARK_SFX_RE = re.compile("_[^_]+_level.xml$")
MRKBL_NAME_RE = re.compile(r"^.*_([^_]+)_level.xml$", re.IGNORECASE)
MRKBL_FNAME_RE = re.compile("^(.*_)([^_]+_level.xml)$", re.IGNORECASE)
MRKBL_ID_RE = re.compile(r"(?<!\S)markable_", re.IGNORECASE)
EMOEXPRESSION_NAME = "emo-expression"
POLARITY = "polarity"
POSITIVE = "positive"
NEGATIVE = "negative"

MSTAT_HEADER_FMT = "{:15s}{:>10s}{:>10s}{:>10s}{:>10s}{:>10s}"
MSTAT_FMT = "{:15s}{:>10d}{:>10d}{:>10d}{:>10d}{:>10.4f}"

XML_HEADER = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE markables SYSTEM "markables.dtd">
"""

EMPTY_SET = set()

BINARY_OVERLAP = 1
PROPORTIONAL_OVERLAP = 2
EXACT_MATCH = 4

statistics = {}


##################################################################
# Methods
def _compute_kappa(a_overlap1, a_total1, a_overlap2, a_total2,
                   a_total_tkns, a_cmp):
    """Compute Cohen's Kappa.

    @param a_overlap1 - number of overlapping annotations in the 1-st
      annotation
    @param a_total1  - total number of markables in the 1-st annotation
    @param a_overlap2 - number of overlapping annotations in the 2-nd
      annotation
    @param a_total2 - total number of markables in the 2-nd annotation
    @param a_total_tkns - total number of tokens in file
    @param a_cmp - scheme used for comparison

    @return float

    """
    assert a_overlap1 <= a_total1, \
        "The numer of matched annotation in the 1-st file" \
        " exceeds the total number of markables."
    assert a_overlap2 <= a_total2, \
        "The numer of matched annotation in the 2-nd file" \
        " exceeds the total number of markables."
    assert a_overlap1 == a_overlap2 or a_cmp & BINARY_OVERLAP, \
        "Different numbers of overlapping tokens for two annotators."
    # compute chance agreement
    if a_total_tkns == 0.0:
        return 0.0
    agreement = float(a_total_tkns - a_total1 + a_overlap1
                      - a_total2 + a_overlap2) / a_total_tkns
    # chances that the first/second annotator randomly annotated a token with
    # that markable
    chance1 = float(a_total1) / a_total_tkns
    chance2 = float(a_total2) / a_total_tkns
    chance = chance1 * chance2 + (1.0 - chance1) * (1.0 - chance2)
    assert chance <= 1.0, \
        "Invalid value of chance agreement: '{:.2f}'".format(kappa)
    # compute Cohen's Kappa
    if chance < 1.0:
        kappa = (agreement - chance) / (1.0 - chance)
    else:
        kappa = 0.0
    assert kappa <= 1.0, "Invalid kappa value: '{:.4f}'".format(kappa)
    return kappa


def _markables2tuples(a_t):
    """
    Convert markables in XML tree to tuples.

    @param a_t - XML tree with elements

    @return list of tuples

    """
    retlist = []
    # return empty list for non-present
    if a_t is None:
        return retlist
    # iterate over elements of XML tree and append them as tuples
    mspan = mname = None
    mattrs = []
    span_w_ids = []
    for mark in a_t.iter():
        # due to presence of namespaces, we can't directly access markable
        # elements, so we hypotethesize them by checking their attributes
        mspan = mark.get("span")
        if not mspan:
            continue
        # get id's of all words covered by the given span
        span_w_ids = parse_span(mspan, a_int_fmt=True)
        assert span_w_ids, "Markable span is empty"
        # obtain the name of the markable
        mname = mark.get("mmax_level")
        # obtain and prune attributes of the markable
        mattrs = mark.attrib
        # # we assume those attributes are not needed as they can be found in
        # # other fields of the tuples
        # del mattrs["span"]
        # del mattrs["mmax_level"]
        # append markable as a tuple to the markable list
        span_w_ids.sort()
        retlist.append([span_w_ids, mname, mattrs])
    # return list of markables sorted by the starting and ending positions of
    # the spans
    return sorted(retlist, key=lambda e: (e[0][0], e[0][-1]))


def _w_id2span(a_w_ids):
    """
    Convert list of word id's to string specification.

    @param a_w_ids - list of word ids as integers

    @return string representation of word id's
    """
    ret_list = []
    if not a_w_ids:
        return ""
    # convert list to a deque
    w_deque = deque(a_w_ids)
    # iterate over all word ids in deque
    prev_w_id = r_start = w_deque.popleft()
    w_id = -1
    while w_deque:
        w_id = w_deque.popleft()
        # if fhe next token id breaks contiguous span, add a range from r_start
        # to prev_w_id or (if no range is available) just a single token for
        # r_start
        if w_id - prev_w_id > 1:
            assert r_start >= 0, "Invalid range start: {:d}".format(rng_start)
            # append range, if previous word id is other than range start
            if prev_w_id != r_start:
                ret_list.append(WRD_PRFX + str(r_start) + WRD_RANGE_SEP
                                + WRD_PRFX + str(prev_w_id))
            else:
                ret_list.append(WRD_PRFX + str(r_start))
            # new range start is the current word id
            r_start = w_id
        prev_w_id = w_id
    # append the final span
    if prev_w_id != r_start:
        ret_list.append(WRD_PRFX + str(r_start) + WRD_RANGE_SEP
                        + WRD_PRFX + str(prev_w_id))
    else:
        ret_list.append(WRD_PRFX + str(r_start))
    # join separate words and ranges by commas
    return WRD_SEP.join(ret_list)


def _make_attrs(a_attrs, a_update_ids=True):
    """Convert a list of attribute name/value pairs to dictionary.

    @param a_attrs - list of attribute name/value pairs
    @param a_update_ids - boolean flag indicating whether ids should be renamed

    @return dictionary of attributes

    """
    retdict = dict(a_attrs)
    # change markable ids if necessary
    if a_update_ids:
        for k, v in retdict.iteritems():
            retdict[k] = MRKBL_ID_RE.sub(r"\g<0>100500", v)
    return retdict


def _add_markable(a_prnt, a_tpl, **a_attrs):
    """Convert markables in XML tree to tuples.

    @param a_prnt - parent XML element to which new element should be appended
    @param a_tpl - tuple containing information about markable
    @param a_attrs - dictionary of additional attributes

    @return XML element representing the markable

    """
    m_w_id, m_name, m_attrs = a_tpl
    mrkbl = _ET.SubElement(a_prnt, MARKABLE, {})
    # change transferred id's and update attributes of the new markable
    mrkbl.attrib.update(_make_attrs(a_tpl[-1]))
    # set word spans of this markable
    mrkbl.attrib["span"] = _w_id2span(m_w_id)
    # set attributes which were provided as markables
    mrkbl.attrib.update(a_attrs)
    return mrkbl


def _is_smiley(a_word):
    """Check if given word is a smiley

    @param a_word - word to be checked

    @return \c true if the word is a smile \c false otherwise

    """
    return bool(SMILEY_RE.match(a_word))


def _is_emoticon(a_w_ids, a_wid2word):
    """
    Check if given markable is assigned to an emoticon

    @param a_w_ids - list of word id's pertaining to markable
    @param a_wid2word - dictionary mapping word indices to words

    @return \c true if the markable is an emoticon \c false otherwise
    """
    return all([_is_smiley(a_wid2word[float(w_id)]) for w_id in a_w_ids])


def _update_stat(a_t1, a_t2, a_n, a_diff1_pos, a_diff1_neg,
                 a_diff2_pos, a_diff2_neg, a_wid2word,
                 a_cmp=BINARY_OVERLAP):
    """Compare annotations present in two XML trees.

    @param a_t1 - first XML tree to compare
    @param a_t2 - second XML tree to compare
    @param a_n - total number of tokens
    @param a_diff1_pos - list for storing agreement statistics about positive
                  emo-expressions in the 1-st annotation
    @param a_diff1_neg - list for storing agreement statistics about negative
                  emo-expressions in the 1-st annotation
    @param a_diff1_pos - list for storing agreement statistics about positive
                  emo-expressions in the 2-nd annotation
    @param a_diff1_neg - list for storing agreement statistics about negative
                  emo-expressions in the 2-nd annotation
    @param a_wid2word - dictionary mapping word indices to words
    @param a_cmp - mode for comparing two spans

    @return \c updated total number of tokens

    """
    # convert markables in files to lists of tuples
    markable_tuples1 = _markables2tuples(a_t1)
    markable_tuples2 = _markables2tuples(a_t2)
    # generate lists all indices in markables
    for ipolarity in (POSITIVE, NEGATIVE):
        if ipolarity == POSITIVE:
            stat1 = a_diff1_pos
            stat2 = a_diff2_pos
        else:
            stat1 = a_diff1_neg
            stat2 = a_diff2_neg

        m_tuples1 = [mt for mt in markable_tuples1
                     if mt[-1][POLARITY] == ipolarity
                     and not _is_emoticon(mt[OFFSET_IDX], a_wid2word)]
        m_tuples2 = [mt for mt in markable_tuples2
                     if mt[-1][POLARITY] == ipolarity
                     and not _is_emoticon(mt[OFFSET_IDX], a_wid2word)]

        m1_word_ids = [w for mt in m_tuples1 for w in mt[0]]
        m2_word_ids = [w for mt in m_tuples2 for w in mt[0]]

        # generate sets of indices in markables
        m1_set = set(m1_word_ids)
        m2_set = set(m2_word_ids)

        if a_cmp & PROPORTIONAL_OVERLAP:
            # get total number of tokens marked with that markable
            stat1[TOTAL_MRKBL_IDX] = len(m1_set)
            stat2[TOTAL_MRKBL_IDX] = len(m2_set)
            # for proportional overlap, the number of overlapping tokens will
            # be the same for both files
            stat1[MATCH_MRKBL_IDX] = stat2[MATCH_MRKBL_IDX] = \
                len(m1_set & m2_set)
        else:
            # get total number of tokens marked with that markable
            if a_cmp & BINARY_OVERLAP:
                stat1[TOTAL_MRKBL_IDX] = len(m1_word_ids)
                stat2[TOTAL_MRKBL_IDX] = len(m2_word_ids)
                # for binary overlap, we consider two spans to agree on all of
                # their tokens, if they have at least one token in common
                w_id_set = None
                # matches1, matches2 = set(), set()
                # populate set of word ids from the 1-st annotation whose spans
                # are overlapping
                for mt1 in m_tuples1:
                    w_id_set = set(mt1[OFFSET_IDX])
                    if w_id_set & m2_set:
                        # matches1.update(w_id_set)
                        stat1[MATCH_MRKBL_IDX] += len(w_id_set)
                # populate set of word ids from the 2-nd annotation whose spans
                # are overlapping
                for mt2 in m_tuples2:
                    w_id_set = set(mt2[OFFSET_IDX])
                    if w_id_set & m1_set:
                        # matches2.update(w_id_set)
                        stat2[MATCH_MRKBL_IDX] += len(w_id_set)
                # UNCOMMENT IF NECESSARY

                # # now, join the two sets and count the number of elements in
                # # them this will be
                # common_matches = matches1.union(matches2)
                # a_diff2[MATCH_MRKBL_IDX] = len(common_matches)
                # # we also need to update the total number of markables in
                # # both annotations to prevent that the number of matched
                # # markables is bigger than the total number of marked tokens
                # # # a_diff1[TOTAL_MRKBL_IDX] = a_diff2[TOTAL_MRKBL_IDX] =
                # # len(m1_set.union(m2_set))
            else:
                # update counters of total words
                # for exact matches, we will simultenously iterate over two
                # lists of markable tuples
                len1, len2 = len(m_tuples1), len(m_tuples2)
                stat1[TOTAL_MRKBL_IDX], stat2[TOTAL_MRKBL_IDX] = len1, len2
                if len1 > len2:
                    max_len, min_len = len1, len2
                else:
                    max_len, min_len = len2, len1
                i = j = 0
                mt1 = mt2 = mt_w1 = mt_w2 = None
                while i < min_len and j < min_len:
                    # obtain word id's for two tuples
                    mt1, mt2 = m_tuples1[i], m_tuples2[j]
                    mt_w1, mt_w2 = mt1[OFFSET_IDX], mt2[OFFSET_IDX]
                    # if the 1-st tuple precedes the 2-nd, increment the 1-st
                    # span
                    if mt_w1[0] < mt_w2[0]:
                        # create new markable tuple for non-matching indices
                        i += 1
                    # if the 2-nd tuple precedes the 1-st, do the opposite
                    elif mt_w1[0] > mt_w2[0]:
                        # create new markable tuple for non-matching indices
                        j += 1
                    # if both spans are equal update the overlap counters
                    elif mt_w1 == mt_w2:
                        stat2[MATCH_MRKBL_IDX] += 1
                    i += 1
                    j += 1
                # the number of overlapping tokens will be the same for both
                # annotators
                stat1[MATCH_MRKBL_IDX] = stat2[MATCH_MRKBL_IDX]
                a_n -= len(m1_set | m2_set)
                a_n += max(len1, len2)
    return a_n


def compute_stat(a_basedata_dir, a_dir1, a_dir2,
                 a_ptrn="", a_cmp=BINARY_OVERLAP):
    """
    Compare markables in two annotation directories.

    @param a_basedata_dir - directory containing basedata for MMAX project
    @param a_dir1 - directory containing markables for the first annotator
    @param a_dir2 - directory containing markables for the second annotator
    @param a_ptrn - shell pattern for markable files
    @param a_cmp  - mode for comparing two annotation spans

    @return \c void
    """
    global statistics
    # find annotation files from first directory
    if a_ptrn:
        dir1_iterator = glob.iglob(a_dir1 + os.sep + a_ptrn)
    else:
        dir1_iterator = os.listdir(a_dir1)
    # iterate over files from the first directory
    f1 = f2 = ""
    basename1 = markname = ""
    basedata_fname = base_key = ""
    fd1 = fd2 = basedata_fd = None
    t1 = t2 = t2_root = None
    f1_out = f2_out = ""
    words = None
    w_id2word = dict()
    annotations = None
    n = 0                       # total number of words in the file

    for f1 in dir1_iterator:
        # get name of second file
        basename1 = os.path.basename(f1)
        print >> sys.stderr, "Processing file '{:s}'".format(f1)
        f2 = a_dir2 + os.sep + basename1
        # open both files for reading
        fd1 = open(a_dir1 + os.sep + basename1, 'r')
        try:
            t1 = _ET.parse(fd1)
        except (IOError, _ET.ParseError):
            t1 = None
        finally:
            fd1.close()
        # read XML information from second file ignoring non-existent, empty,
        # and wrong formatted files
        try:
            fd2 = open(f2, 'r')
            try:
                t2 = _ET.parse(fd2)
            finally:
                fd2.close()
        except (IOError, _ET.ParseError):
            t2 = None

        if t1 is None or t2 is None:
            continue
        # determine the name of the markable for which we should calculate
        # annotations
        mname = MRKBL_NAME_RE.match(basename1).group(1).lower()
        if mname.lower() != "emo-expression":
            continue
        mname_pos = mname + "-pos"
        mname_neg = mname + "-neg"
        # prepare containers for storing information about matching and
        # mismatching annotations
        # the 0-th element in the list is the number of matching annotations,
        # the 1-st element is the total number of tokens annotated with that
        # markables, the 2-nd element is a list of annotation span tuples which
        # are different in another annotation
        anno1_pos = [0, 0]
        anno1_neg = [0, 0]
        anno2_pos = [0, 0]
        anno2_neg = [0, 0]
        base_key = MARK_SFX_RE.sub("", basename1)

        # obtain number of words from basedata file
        basedata_fname = a_basedata_dir + os.sep + base_key + BASEDATA_SFX
        basedata_fd = open(basedata_fname, "r")
        # get total number of words in a file
        idoc = _ET.parse(basedata_fd).getroot()
        words = idoc.findall("word")
        n = len(words)
        for w in words:
            w_id2word[float(WRD_PRFX_RE.sub("", w.get("id")))] = w.text
        basedata_fd.close()
        # compare two XML trees
        n = _update_stat(t1, t2, n, anno1_pos, anno1_neg,
                         anno2_pos, anno2_neg, w_id2word, a_cmp)
        # assign statistics
        statistics[base_key] = {"tokens": n, "annotators":
                                [{mname_pos: anno1_pos, mname_neg: anno1_neg},
                                 {mname_pos: anno2_pos, mname_neg: anno2_neg}]}
        w_id2word.clear()


def print_stat(a_cmp):
    """
    Output statistics about agreement measure.

    @param a_cmp - scheme used for comparison

    @return void
    """
    markable_dic = {}
    anno_dic1 = anno_dic2 = None
    m_stat1 = m_stat2 = markable_stat = None
    m_names = []
    N = n = 0                   # N - total number of tokens in all files
    overlap1 = overlap2 = 0
    total1 = total2 = 0
    kappa = 0
    # output Kappa statistics for files and simultaneously update dictionary
    # for total markable statistics
    for fname, fstat_dic in statistics.iteritems():
        print "File: '{:s}'".format(fname)
        # number of tokens in file
        n = fstat_dic["tokens"]
        N += n
        # iterate over markables in that file
        # print repr(fstat_dic["annotators"])
        anno_dic1, anno_dic2 = fstat_dic["annotators"]
        assert set(anno_dic1.keys()) == set(anno_dic2.keys()), \
            "Unmatched number of markables for two annotators" \
            " '{:s}'\nvs.\n{:s}.".format(repr(anno_dic1.keys()),
                                         repr(anno_dic2.keys()))
        # iterate over markables
        for m_name, m_stat1 in anno_dic1.iteritems():
            m_stat2 = anno_dic2[m_name]
            overlap1, overlap2 = \
                m_stat1[MATCH_MRKBL_IDX], m_stat2[MATCH_MRKBL_IDX]
            total1, total2 = m_stat1[TOTAL_MRKBL_IDX], m_stat2[TOTAL_MRKBL_IDX]
            # compute kappa's
            kappa = _compute_kappa(overlap1, total1,
                                   overlap2, total2, n, a_cmp)
            print "Markable: {:s}".format(m_name)
            print "Matched: {:d}; Total marked: {:d}; Kappa:" \
                " {:.2f}".format(overlap1, total1, kappa)
            # update dictionary of markables
            if m_name in markable_dic:
                markable_stat = markable_dic[m_name]
                markable_stat[OVERLAP1_IDX] += overlap1
                markable_stat[TOTAL1_IDX] += total1
                markable_stat[OVERLAP2_IDX] += overlap2
                markable_stat[TOTAL2_IDX] += total2
            else:
                markable_dic[m_name] = [overlap1, total1, overlap2, total2]
        print "=================================" \
            "================================="
    # output statistics for markables
    print "STATISTICS FOR MARKABLES"
    print MSTAT_HEADER_FMT.format("Markable", "Overlap1", "Total1",
                                  "Overlap2", "Total2", "Kappa")
    for m_name, m_stat in markable_dic.iteritems():
        kappa = _compute_kappa(m_stat[OVERLAP1_IDX], m_stat[TOTAL1_IDX],
                               m_stat[OVERLAP2_IDX], m_stat[TOTAL2_IDX],
                               N, a_cmp)
        print MSTAT_FMT.format(m_name, m_stat[OVERLAP1_IDX],
                               m_stat[TOTAL1_IDX], m_stat[OVERLAP2_IDX],
                               m_stat[TOTAL2_IDX], kappa)


def main():
    """
    Main method for measuring agreement and marking differences in corpus.
    """
    # process arguments
    argparser = argparse.ArgumentParser(description="Script for measuring"
                                        " agreement between two annotated"
                                        " MMAX projects and marking difference"
                                        " between them.")
    argparser.add_argument("basedata_dir",
                           help="directory containing basedata (tokens)"
                           " for MMAX project")
    argparser.add_argument("directory1",
                           help="directory containing markables from"
                           " the first annotator")
    argparser.add_argument("directory2",
                           help="directory containing markables"
                           " from the second annotator")
    # agreement schemes for spans
    argparser.add_argument("-b", "--binary-overlap",
                           help="consider two spans to agree on all of tokens"
                           " of their respective spans if they overlap by at"
                           "least one token (default comparison mode)",
                           action="store_const", const=BINARY_OVERLAP,
                           default=0)
    argparser.add_argument("-p", "--proportional-overlap",
                           help="count as agreement only tokens that actually"
                           " ovelap in two spans", action="store_const",
                           const=PROPORTIONAL_OVERLAP, default=0)
    argparser.add_argument("-x", "--exact-match",
                           help="consider two spans to agree if they have"
                           " exactly the same boundaries",
                           action="store_const",
                           const=EXACT_MATCH, default=0)
    # additional flags
    argparser.add_argument("--pattern",
                           help="shell pattern for files with markables",
                           type=str, default="*emo-expression*")
    args = argparser.parse_args()

    # check if comparison scheme is specified
    cmp_scheme = args.binary_overlap | args.proportional_overlap \
        | args.exact_match
    if cmp_scheme == 0:
        cmp_scheme = BINARY_OVERLAP
    # check existence and readability of directory
    dir1 = args.directory1
    dir2 = args.directory2

    assert os.path.isdir(dir1) and os.access(dir1, os.X_OK), \
        "Directory '{:s}' does nor exist or cannot be accessed.".format(dir1)
    assert os.path.isdir(dir2) and os.access(dir2, os.X_OK), \
        "Directory '{:s}' does nor exist or cannot be accessed.".format(dir2)

    # compare the directory contents and edit files if necessary
    compute_stat(args.basedata_dir, dir1, dir2,
                 a_ptrn=args.pattern, a_cmp=cmp_scheme)

    print_stat(cmp_scheme)

##################################################################
# Main
if __name__ == "__main__":
    main()
