import sys
import os
import json
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import datetime

import argparse
import logging

from time import sleep

from pymso5000.mso5000 import MSO5000

def parseArguments():
    ap = argparse.ArgumentParser(description = "MSO5000 data fetcher")
    ap.add_argument("-o", "--out", type=str, required=False, default=None, action='append', nargs="*", help="Add npz, svg or png output file (determined by extension")

    ap.add_argument("-m", "--host", type=str, required=False, default=None, help="Specify the hostname or IP address of the MSO. If not specified will be loaded from the configuration file")
    ap.add_argument("-p", "--port", type=int, required=False, default=5555, help="Network port of the MSO (default 5555)")

    ap.add_argument("-s", "--stat", type=str, required=False, default=None, action='append', nargs="*", help="Statistics to evaluate (mean)")
    ap.add_argument("-v", "--show", action="store_true", help="Show the plot using matplotlib")

    ap.add_argument("--endis", action="store_true", help="Enable requested channels, disable others")
    ap.add_argument("-d", "--differential", action="store_true", help="Perform a differential measurement by first aquiring the background, then the foreground and performing subtraction")
    ap.add_argument("--delay", type=int, required=False, default=10, help="Delay for background measurement (typical 10 seconds)")
    ap.add_argument("--noplot", type=int, required=False, default=None, action='append', nargs="*", help="Disable plotting for the specified channel")

    ap.add_argument("--plottitle", type=str, required=False, default="MSO5000", help="Set plot title")
    ap.add_argument("--xlabel", type=str, required=False, default=None, help="Timebase axis label")
    ap.add_argument("--ylabel", type=str, required=False, default=None, help="Y axis label")
    ap.add_argument("--ylabeld", type=str, required=False, default=None, help="Difference Y axis label")

    ap.add_argument("--loglevel", type=str, required=False, default="ERROR", help="Loglevel (CRITICAL, ERROR, WARNING, INFO, DEBUG)")
    ap.add_argument("--logfile", type=str, required=False, default=None, help="Log into the specified logfile instead of the console")

    ap.add_argument("--noautoscale", action = "store_true", help="Disable automatic scaling")

    ap.add_argument("rest", nargs=argparse.REMAINDER)

    args = ap.parse_args()

    # Validate we know the filetypes of -o if any
    if args.out is not None:
        for fname in args.out:
            if len(fname) < 1:
                print(f"Invalid output filename {fname} supplied")
                sys.exit(1)
            fname = fname[0]
            if len(fname) < 4:
                print(f"Invalid output filename {fname} supplied")
                sys.exit(1)
            if fname[-4:] not in [ ".png", ".npz", ".svg" ]:
                print(f"File format of {fname} not known by extension")
                sys.exit(1)

    loglvls = {
        "DEBUG" : logging.DEBUG,
        "INFO" : logging.INFO,
        "WARNING" : logging.WARNING,
        "ERROR" : logging.ERROR,
        "CRITICAL" : logging.CRITICAL
    }
    if not args.loglevel.upper()in loglvls:
        print("Unknown loglevel {args.loglevel}")
        sys.exit(1)

    logger = logging.getLogger()
    logger.setLevel(loglvls[args.loglevel.upper()])
    if args.logfile is not None:
        logger.addHandler(logging.FileHandler(args.logfile))
        logger.addHandler(logging.StreamHandler(sys.stderr))
    else:
        logger.addHandler(logging.StreamHandler(sys.stderr))

    return (args, logger)

def loadConfigFile(cfname = ".config/mso5000.cfg"):
    cfgPath = os.path.join(Path.home(), cfname)
    try:
        with open(cfgPath) as cfgFile:
            cfg = json.load(cfgFile)
    except FileNotFoundError:
        return None
    except JSONDecodeError as e:
        print(f"Failed to load configuration file {cfgname}")
        print(e)
        sys.exit(1)

    return cfg

def getScaleFactorAndPrefix(v):
    prefixlist = [
        (1e12, "T"),
        (1e9, "G"),
        (1e6, "M"),
        (1e3, "k"),
        (1, ""),
        (1e-3, "m"),
        (1e-6, "u"),
        (1e-9, "n"),
        (1e-12, "p"),
        (1e-15, "f")
    ]

    for i in range(len(prefixlist)):
        if v > prefixlist[i][0]:
            return (1.0 / prefixlist[i][0], prefixlist[i][1])
    return (1.0 / prefixlist[-1][0], prefixlist[-1][1])

def main():
    args, logger= parseArguments()
    cfgFile = loadConfigFile()

    if len(args.rest) < 1:
        print(f"No channels specified. See usage with {sys.argv[0]} --help")
        sys.exit(1)

    if (args.host is None) and (cfgFile is not None):
        if "host" in cfgFile:
            args.host = cfgFile["host"]
        if "port" in cfgFile:
            args.port = cfgFile["port"]

    # Now conenct to the MSO
    logger.debug(f"Connecting to {args.host} at port {args.port}")
    with MSO5000(
        address = args.host,
        port = args.port,
        useNumpy = True
    ) as mso:
        logger.debug("Connected")

        # Enable the requested channels, disable the others
        chRequested = []
        chNoplot = []
        requestedStats = []

        for ch in args.rest:
            try:
                nch = int(ch)
                if (nch < 1) or (nch > 4):
                    print(f"Invalid channel number {nch}")
                    sys.exit(1)
                chRequested.append(nch - 1)
            except ValueError:
                print(f"Invalid channel number {ch}")
                sys.exit(1)
        if args.noplot is not None:
            for ch in args.noplot:
                try:
                    nch = int(ch[0])
                    if (nch < 1) or (nch > 4):
                        print(f"Invalid channel number {nch}")
                        sys.exit(1)
                    chNoplot.append(nch - 1)
                except ValueError:
                    print(f"Invalid channel number {ch}")
                    sys.exit(1)
        if args.stat is not None:
            for st in args.stat:
                if st[0] in [ "mean", "fft", "ifft", "correlate", "autocorrelate" ]:
                    requestedStats.append(st[0])
                else:
                    print(f"Unknown statistics {st}")

        if args.endis:
            for i in range(4):
                if i in chRequested:
                    logger.info(f"Enabling channel {i+1}")
                    mso.set_channel_enable(i, True)
                else:
                    logger.info(f"Disabling channel {i+1}")
                    mso.set_channel_enable(i, False)

        #Query the waveform ...
        logger.info("Gathering data")
        data = mso.query_waveform(chRequested, stats = requestedStats)
        dataBG = None
        dataDiff = None

        if args.differential:
            logger.info(f"Sleeping for {args.delay} seconds till gathering background data")
            sleep(args.delay)

            logger.info("Gathering background data")
            dataBG = mso.query_waveform(chRequested, stats = requestedStats)

            dataDiff = {}
            for ch in chRequested:
                dataDiff[f"y{ch}"] = data[f"y{ch}"] - dataBG[f"y{ch}"]

        # Plot figures if a plot is requested or show has been enabled
        doPlot = False
        if args.show:
            doPlot = True
        if args.out is not None:
            for fname in args.out:
                fname = fname[0]
                if fname[-4:] in [ ".svg", ".png" ]:
                    doPlot = True
                if fname[-4:] in [ ".npz" ]:
                    # Store npz
                    np.savez(fname, data = data, background = dataBG, diffdata = dataDiff)
                    logger.info(f"Stored {fname}")
        else:
            # Always plot if we don't write output files ...
            doPlot = True

        if doPlot:
            # Determine the scaling factors for all data ...
            maxYval = 0
            for ich in chRequested:
                if ich not in chNoplot:
                    newmax = np.max(data[f"y{ich}"])
                    newmin = np.min(data[f"y{ich}"])
                    maxYval = np.max((newmax, maxYval, np.abs(newmin)))
                    if dataDiff is not None:
                        newmax = np.max(dataBG[f"y{ich}"])
                        newmin = np.min(dataBG[f"y{ich}"])
                        maxYval = np.max((newmax, maxYval, np.abs(newmin)))
            sfY, sfYLabel = getScaleFactorAndPrefix(maxYval)

            if dataDiff is not None:
                maxYDval = 0
                for ich in chRequested:
                    if ich not in chNoplot:
                        newmax = np.max(dataDiff[f"y{ich}"])
                        newmin = np.min(dataDiff[f"y{ich}"])
                        maxYDval = np.max((newmax, np.abs(newmin), maxYDval))
                sfYD, sfYDLabel = getScaleFactorAndPrefix(maxYDval)

            sfX, sfXLabel = getScaleFactorAndPrefix(np.max(data["x"]))

            if args.noautoscale:
                sfX, sfXLabel = 1, ""
                sfY, sfYLabel = 1, ""
                sfYD, sfYDLabel = 1, ""

            xlabel = "Time "
            ylabel = "Signal "
            ylabeld = "Difference signal "

            if args.xlabel:
                xlabel = f"{args.xlabel} "
            if args.ylabel:
                ylabel = f"{args.ylabel} "
            if args.ylabeld:
                ylabeld = f"{args.ylabeld} "

            nplt = 1
            if dataDiff is not None:
                nplt = 2

            fig, ax = plt.subplots(nplt, figsize=(6.4, 4.8 * nplt))

            fig.suptitle(args.plottitle)

            if nplt == 1:
                for ich in chRequested:
                    if ich not in chNoplot:
                        ax.plot(data["x"] * sfX, data[f"y{ich}"] * sfY, label = f"Channel {ich+1}")
                        if dataBG is not None:
                            ax.plot(dataBG["x"] * sfX, dataBG[f"y{ich}"] * sfY, label = f"Background channel {ich+1}")
                ax.set_xlabel(f"{xlabel}[{sfXLabel}s]")
                ax.set_ylabel(f"{ylabel}[{sfYLabel}V]")
                ax.grid()
                ax.legend()
            else:
                for ich in chRequested:
                    if ich not in chNoplot:
                        ax[0].plot(data["x"] * sfX, data[f"y{ich}"] * sfY, label = f"Channel {ich+1}")
                        if dataBG is not None:
                            ax[0].plot(data["x"] * sfX, data[f"y{ich}"] * sfY, label = f"Background channel {ich+1}")
                ax[0].set_xlabel(f"{xlabel}[{sfXLabel}s]")
                ax[0].set_ylabel(f"{ylabel}[{sfYLabel}V]")
                ax[0].grid()
                ax[0].legend()

                if dataDiff is not None:
                    for ich in chRequested:
                        if ich not in chNoplot:
                            ax[1].plot(data["x"] * sfX, dataDiff[f"y{ich}"] * sfYD, label = f"Difference channel {ich+1}")
                    ax[1].set_xlabel(f"{xlabel}[{sfXLabel}s]")
                    ax[1].set_ylabel(f"{ylabeld}[{sfYLabel}V]")
                    ax[1].grid()
                    ax[1].legend()

            if args.out is not None:
                for fn in args.out:
                    fname = fn[0]
                    if fname[-4:] in [ ".svg", ".png" ]:
                        plt.savefig(fname)
                        logger.info(f"Written plot {fname}")

            if args.show or (args.out is None):
                plt.show()
                

if __name__ == "__main__":
    main()
