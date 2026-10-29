"""Registry mapping expansion dataset ids to their acquirers."""

from laris.corpus.acquisition.sources.cc100 import acquire_cc100_vi
from laris.corpus.acquisition.sources.expansion import (
    acquire_fever,
    acquire_hotpotqa,
    acquire_vinli,
    acquire_viquad_v2,
    acquire_vists,
    record_vi_paws_status,
)

EXPANSION_ACQUIRERS = {
    "VINLI": acquire_vinli,
    "VISTS": acquire_vists,
    "VI-PAWS": record_vi_paws_status,
    "CC100-VI-CLEAN": acquire_cc100_vi,
    "HOTPOTQA": acquire_hotpotqa,
    "FEVER": acquire_fever,
    "UIT-VIQUAD-V2": acquire_viquad_v2,
}
