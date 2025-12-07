from argparse import ArgumentParser

from practiso_mcp import main

parser = ArgumentParser()
parser.add_argument("--transport", default="stdio", help="communication method this server uses", choices=['stdio', 'streamable-http', 'sse'])
args = parser.parse_args()
main(args.transport)
