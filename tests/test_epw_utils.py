# -*- coding: utf-8 -*-
"""
tests/test_epw_utils.py
==========================

Unit tests for :func:`pyweatherfiles.epw_utils.classify_epw_files`,
including the ``'city'`` named-group alias added in Fase 4 of
``INFORME_REVISION_GENERAL.md`` (§3.3/§6) so that
``EpwTrendAnalyzer.discover_files()`` can reuse this helper — originally
written only for ``EpwGroupTrendAnalyzer``, whose regex names the
classification group ``'group'`` instead of ``'city'``.
"""

import pytest

from pyweatherfiles.epw_utils import DEFAULT_EPW_GROUP_YEAR_PATTERN, classify_epw_files


class TestClassifyEpwFilesGroupAlias:
    def test_classifies_with_default_group_pattern(self):
        paths = ["/data/granada_2005.epw", "/data/granada_2006.epw", "/data/seville_2005.epw"]
        result = classify_epw_files(epw_paths=paths)
        assert set(result.keys()) == {"granada", "seville"}
        assert result["granada"][2005].endswith("granada_2005.epw")
        assert result["granada"][2006].endswith("granada_2006.epw")
        assert result["seville"][2005].endswith("seville_2005.epw")

    def test_classifies_with_city_named_group(self):
        # EpwTrendAnalyzer's TrendConfig.filename_regex names the group 'city'.
        city_pattern = r"^(?P<city>[A-Za-z]+)_(?P<year>\d{4})\.epw$"
        paths = ["/data/madrid_2019.epw", "/data/madrid_2020.epw"]
        result = classify_epw_files(epw_paths=paths, filename_pattern=city_pattern)
        assert set(result.keys()) == {"madrid"}
        assert set(result["madrid"].keys()) == {2019, 2020}

    def test_group_alias_takes_precedence_over_city(self):
        # If a (contrived) pattern defines both, 'group' wins (documented
        # fallback order: group -> city -> filename stem).
        pattern = r"^(?P<group>[A-Za-z]+)-(?P<city>[A-Za-z]+)_(?P<year>\d{4})\.epw$"
        result = classify_epw_files(epw_paths=["/data/zoneA-madrid_2020.epw"], filename_pattern=pattern)
        assert set(result.keys()) == {"zoneA"}

    def test_skips_non_matching_files_with_warning(self, capsys):
        paths = ["/data/granada_2005.epw", "/data/not_matching.txt"]
        result = classify_epw_files(epw_paths=paths)
        assert list(result.keys()) == ["granada"]
        captured = capsys.readouterr()
        assert "WARNING" in captured.out

    def test_raises_without_dir_or_paths(self):
        with pytest.raises(ValueError):
            classify_epw_files()

    def test_default_pattern_matches_expected_regex(self):
        assert DEFAULT_EPW_GROUP_YEAR_PATTERN == r'^(?P<group>[a-zA-Z]+)_(?P<year>\d{4})\.epw$'

