import argparse
parser = argparse.ArgumentParser(description="d", prog="p", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument("--n", type=int, default=3, help="n", required=False)
parser.add_argument("-v", "--verbose", action="store_true")
sub = parser.add_subparsers(dest="cmd")
sp = sub.add_parser("run", help="r")
sp.add_argument("x", nargs="?", choices=["a", "b"])
args = parser.parse_args(["--n", "4", "run", "a"])
print(args.n, args.verbose, args.cmd)
