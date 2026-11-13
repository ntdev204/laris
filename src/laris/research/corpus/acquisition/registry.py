"""Registry mapping expansion dataset ids to their acquirers."""

from laris.research.corpus.acquisition.sources.cc100 import acquire_cc100_vi
from laris.research.corpus.acquisition.sources.english_hf import english_acquirers
from laris.research.corpus.acquisition.sources.expansion import (
    acquire_fever,
    acquire_hotpotqa,
    acquire_scifact,
    acquire_vinli,
    acquire_viquad_v2,
    acquire_vists,
)
from laris.research.corpus.acquisition.sources.s2orc import acquire_s2orc

EXPANSION_ACQUIRERS = {
    "VINLI": acquire_vinli,
    "VISTS": acquire_vists,
    "CC100-VI-CLEAN": acquire_cc100_vi,
    "HOTPOTQA": acquire_hotpotqa,
    "FEVER": acquire_fever,
    "UIT-VIQUAD-V2": acquire_viquad_v2,
    "SCIFACT": acquire_scifact,
    "S2ORC-GENERAL-LM": lambda: acquire_s2orc("01"),
    "S2ORC-STEM": lambda: acquire_s2orc("02"),
}


# English stage-1 replacement sources (D46 / ADR-022); configured in configs/data/english_sources.yaml.
# They are fetched only on request (--only ID ... or --english-all), never by a default full run.
ENGLISH_ACQUIRERS = english_acquirers()
