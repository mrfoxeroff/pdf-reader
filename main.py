"""Entry point: python main.py [file.pdf ...]"""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from pdfreader.app import main

    sys.exit(main())
