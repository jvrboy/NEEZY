"""All eight TideForge indicators registered in one import."""

from neezy_backend.lab.vendors.tideforge.indicators.cc import CC
from neezy_backend.lab.vendors.tideforge.indicators.edi import EDI
from neezy_backend.lab.vendors.tideforge.indicators.fscr import FSCR
from neezy_backend.lab.vendors.tideforge.indicators.mdr import MDR
from neezy_backend.lab.vendors.tideforge.indicators.srp import SRP
from neezy_backend.lab.vendors.tideforge.indicators.tdgz import TDGZ
from neezy_backend.lab.vendors.tideforge.indicators.tis import TIS
from neezy_backend.lab.vendors.tideforge.indicators.vbo import VBO

ALL = {cls.NAME: cls for cls in (EDI, VBO, FSCR, TDGZ, TIS, MDR, SRP, CC)}

__all__ = ["EDI", "VBO", "FSCR", "TDGZ", "TIS", "MDR", "SRP", "CC", "ALL"]
