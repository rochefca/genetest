"""
"""

# This file is part of project_x.
#
# This work is licensed under the Creative Commons Attribution-NonCommercial
# 4.0 International License. To view a copy of this license, visit
# http://creativecommons.org/licenses/by-nc/4.0/ or send a letter to Creative
# Commons, PO Box 1866, Mountain View, CA 94042, USA.


import os
from collections import namedtuple

import numpy as np
import pandas as pd
from genipe.formats.index import get_index, get_open_func

from .core import GenotypesContainer, Representation, MarkerGenotypes


__copyright__ = "Copyright 2016, Beaulieu-Saucier Pharmacogenomics Centre"
__license__ = "Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)"


__all__ = ["Impute2Genotypes"]


_Impute2Line = namedtuple("_Impute2Line",
                          ["marker", "chrom", "pos", "a1", "a2", "prob"])


class Impute2Genotypes(GenotypesContainer):
    def __init__(self, impute2_file, sample_file):
        """Instantiate a new Impute2Genotypes object.

        Args:
            impute2_file (str): The name of the IMPUTE2 file.
            sample_file (str): The name of the sample file.

        """
        # Reading the samples
        self.samples = pd.read_csv(sample_file, sep=" ", skiprows=2,
                                   names=["fid", "iid", "missing", "father",
                                          "mother", "sex", "plink_geno"])

        # We want to set the index for the samples
        try:
            self.samples = self.samples.set_index("iid", verify_integrity=True)

        except ValueError:
            self.samples["fid_iid"] = [
                "{fid}_{iid}".format(fid=fid, iid=iid)
                for fid, iid in zip(self.samples.fid, self.samples.iid)
            ]
            self.samples = self.samples.set_index("fid_iid",
                                                  verify_integrity=True)

        # The IMPUTE2 file
        self._impute2_file = get_open_func(impute2_file)(impute2_file, "r")

        # If we have an index, we read it
        self._impute2_index = None
        if os.path.isfile(impute2_file + ".idx"):
            self._impute2_index = get_index(
                impute2_file,
                cols=[0, 1, 2],
                names=["chrom", "name", "pos"],
                sep=" ",
            ).set_index("name", verify_integrity=True)

    def close(self):
        if self._impute2_file:
            self._impute2_file.close()

    def __repr__(self):
        """The string representation."""
        return "Impute2Genotypes({:,d} samples)".format(
            self.samples.shape[0],
        )

    def get_genotypes(self, marker, representation=Representation.DOSAGE,
                      prob_t=0.9):
        """Returns a dataframe of genotypes encoded using the provided model.

        Args:
            marker (str): A marker ID (e.g. rs123456).
            representation (str): A valid genotype representation format (e.g.
                                  genotypes.core.REPRESENTATION.ADDITIVE).
            prob_t (float): The probability threshold for which genotypes will
                            be set as missing.

        Returns:
            Genotypes: A named tuple containing the dataframe with the encoded
                       genotypes for all samples (the index of the dataframe
                       will be the sample IDs), the minor and major alleles.

        """
        self.check_representation(representation)

        if self._impute2_index is None:
            raise NotImplementedError("Not implemented when IMPUTE2 file is "
                                      "not indexed (see genipe)")

        # Reading the probabilities
        self._impute2_file.seek(int(self._impute2_index.loc[marker, "seek"]))
        marker_info = self._parse_impute2_line(self._impute2_file.readline())

        # Creating the dosage data
        dosage = self.create_geno_df(
            genotypes=self._compute_dosage(marker_info.prob, prob_t),
            samples=self.samples.index,
        )

        # Checking the format is fine
        dosage, minor, major = self.check_genotypes(
            genotypes=dosage,
            minor=marker_info.a2,
            major=marker_info.a1,
        )

        # Returning the value as DOSAGE representation
        if representation == Representation.DOSAGE:
            return MarkerGenotypes(genotypes=dosage, marker=marker,
                                   chrom=self.encode_chrom(marker_info.chrom),
                                   pos=marker_info.pos,
                                   major=major, minor=minor)

        # Normal additive values are necessary for ADDITIVE and GENOTYPIC
        geno = self.dosage2additive(dosage)

        # Returning the value as ADDITIVE representation
        if representation == Representation.ADDITIVE:
            return MarkerGenotypes(genotypes=geno, marker=marker,
                                   chrom=self.encode_chrom(marker_info.chrom),
                                   pos=marker_info.pos, major=major,
                                   minor=minor)

        # Returning the value as GENOTYPIC representation
        if representation == Representation.GENOTYPIC:
            return MarkerGenotypes(genotypes=self.additive2genotypic(geno),
                                   chrom=self.encode_chrom(marker_info.chrom),
                                   pos=marker_info.pos, marker=marker,
                                   major=major, minor=minor)

    def iter_marker_genotypes(self, representation=Representation.DOSAGE,
                              prob_t=0.9):
        """Returns a dataframe of genotypes encoded using the provided model.

        Args:
            representation (str): A valid genotype representation format (e.g.
                                  genotypes.core.REPRESENTATION.ADDITIVE).
            prob_t (float): The probability threshold for which genotypes will
                            be set as missing.

        Returns:
            Genotypes: A named tuple containing the dataframe with the encoded
                       genotypes for all samples (the index of the dataframe
                       will be the sample IDs), the minor and major alleles.

        """
        self.check_representation(representation)

        for line in self._impute2_file:
            # Reading the probabilities
            marker_info = self._parse_impute2_line(line)

            # Creating the dosage data
            dosage = self.create_geno_df(
                genotypes=self._compute_dosage(marker_info.prob, prob_t),
                samples=self.samples.index,
            )

            # Checking the format is fine
            dosage, minor, major = self.check_genotypes(
                genotypes=dosage,
                minor=marker_info.a2,
                major=marker_info.a1,
            )

            # Returning the value as DOSAGE representation
            if representation == Representation.DOSAGE:
                yield MarkerGenotypes(
                    genotypes=dosage,
                    marker=marker_info.marker,
                    chrom=self.encode_chrom(marker_info.chrom),
                    pos=marker_info.pos,
                    major=major,
                    minor=minor,
                )

            # Normal additive values are necessary for ADDITIVE and GENOTYPIC
            geno = self.dosage2additive(dosage)

            # Returning the value as ADDITIVE representation
            if representation == Representation.ADDITIVE:
                yield MarkerGenotypes(
                    genotypes=geno,
                    marker=marker_info.marker,
                    chrom=self.encode_chrom(marker_info.chrom),
                    pos=marker_info.pos,
                    major=major,
                    minor=minor,
                )

            # Returning the value as GENOTYPIC representation
            if representation == Representation.GENOTYPIC:
                yield MarkerGenotypes(
                    genotypes=self.additive2genotypic(geno),
                    chrom=self.encode_chrom(marker_info.chrom),
                    pos=marker_info.pos,
                    marker=marker_info.marker,
                    major=major,
                    minor=minor,
                )

    @staticmethod
    def _parse_impute2_line(line):
        """Parses an IMPUTE2 line (a single marker).

        Args:
            line (str): An IMPUTE2 line.

        Returns:
            _Impute2Line: A named tuple containing information about the
                          variation (including the probability matmrix).
        """
        # Splitting
        row = line.rstrip("\r\n").split(" ")

        # Constructing the probabilities
        prob = np.array(row[5:], dtype=float)
        prob.shape = (prob.shape[0] // 3, 3)

        return _Impute2Line(marker=row[1], chrom=row[0], pos=int(row[2]),
                            a1=row[3], a2=row[4], prob=prob)

    @staticmethod
    def _compute_dosage(prob, prob_t):
        """Computes the dosage from a probability matrix (IMPUTE2).

        Args:
            prob (numpy.ndarray): The probability matrix.
            prob_t (float): The probability threshold, for which lower values
                            will be set as missing.

        Returns:
            numpy.ndarray: The dosage vector.

        """
        dosage = 2 * prob[:, 2] + prob[:, 1]

        if prob_t > 0:
            dosage[~np.any(prob >= prob_t, axis=1)] = np.nan

        return dosage
