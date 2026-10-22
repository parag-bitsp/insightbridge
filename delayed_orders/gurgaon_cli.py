"""Host entry point for the separate Gurgaon development pack; shared campaign cap."""
from .gurgaon import GURGAON_CASES, GurgaonEvidence, validate_pack
from .investigation_cli import main

if __name__=='__main__':
    raise SystemExit(main(case_ids=GURGAON_CASES,evidence_type=GurgaonEvidence,integrity=validate_pack))
