"""Host-side CLI. Evidence queries themselves never export or write files."""
import argparse
import json
import sys
from .baseline import analyze
from .evidence import AccessDenied, DataError, DEVELOPMENT_CASES, Evidence


def main():
    parser = argparse.ArgumentParser(description='Read-only deterministic analysis of development fixtures')
    parser.add_argument('--case', required=True, choices=DEVELOPMENT_CASES)
    args = parser.parse_args()
    try:
        result = analyze(Evidence(args.case))
    except (AccessDenied, DataError, OSError, ValueError, KeyError) as error:
        print(json.dumps({'status':'failed','case_id':args.case,'error':str(error)}),file=sys.stderr)
        return 1
    print(json.dumps(result,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
