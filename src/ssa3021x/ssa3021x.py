from labdevices.exceptions import CommunicationError_ProtocolViolation, CommunicationError_Timeout, CommunicationError_NotConnected
from labdevices.spectrumanalyzer import RFPowerLevel, SpectrumAverageUnit, SpectrumAnalyzer
from labdevices.scpi import SCPIDeviceEthernet
from labdevices.siunits import SiUtils, SIUNIT

from time import sleep

import atexit
from enum import Enum

class SSA3021X(SpectrumAnalyzer):
    def __init__(
            self,

            address = None,
            port = 5025,
            logger = None,

            useNumpy = False
    ):
        if useNumpy:
            import numpy as np

        self._scpi = SCPIDeviceEthernet(address, port, logger)
        self._usedConnect = False
        self._usedContext = False
        self._useNumpy = useNumpy

        # Call base class constructor ...

        atexit.register(self.__close)

    def _connect(self, address = None, port = None):
        if self._scpi.connect():
            # Ask for idntity and verify
            v = self._id()
            # Set format to ASCII
            self._set_dataformat(0)
            return True
        else:
            return False

    def _disconnect(self):
        self._scpi.disconnect()
    def _isConnected(self):
        return self._scpi.isConnected()

    def __enter__(self):
        if self._usedConnect:
            raise ValueError("Cannot use context management on connected port")
        self._connect()
        self._usesContext = True
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.__close()
        self._usesContext = False

    def __close(self):
        atexit.unregister(self.__close)

    def _id(self):
        res = self._scpi.scpiQuery("*IDN?")
        res = res.split(",")
        if len(res) != 4:
            raise CommunicationError_ProtocolViolation("IDN string does not follow Siglents layout")
        if res[0] != "Siglent Technologies":
            raise CommunicationError_ProtocolViolation(f"IDN returned manufacturer {res[0]}")
        if res[1] != "SSA3021X":
            raise CommunicationError_ProtocolViolation(f"IDN does not identify SSA3021X device")

        ver = res[3].split(".")

        return {
            'type' : res[1],
            'serial' : res[2],
            'version' : [
                ver[0],
                ver[1],
                ver[2][0]
            ]
        }
    def _serial(self):
        return self._id()['serial']

    def _set_dataformat(self, fmt = 0):
        # Supporting ASCII or binary
        if fmt == 0:
            self._scpi.scpiCommand(":FORM ASC")
        elif fmt == 1:
            self._scpi.scpiCommand(":FORM REAL")

    def _plot_trace(self, traceidx = 0, legend = None, ax = None, show = False, title = None, scale = SISCALE.ONE):
        import matplotlib.pyplot as plt

        if not isinstance(scale, SISCALE):
            raise ValueError("Scalingfactor has to be an instance of SISCALE")

        scalef = 1e6
        scaleprefix = "M"

        if ax is None:
            fig, ax = plt.subplots()

        data = self._query_trace(traceidx = traceidx)

        if not isinstance(traceidx, list) and not isinstance(traceidx, tuple):
            # Only a single one ... make a list and use for loop anyways
            traceidx = [ traceidx ]
            if legend is not None:
                legend = [ legend ]
        else:
            if legend is not None:
                if len(legend) != len(traceidx):
                    raise ValueError("Number of legends does not match number of traces")

        for itrdata, trdata in enumerate(data['data']):
            curlegend = f"Trace {trdata['trace']}"
            if legend is not None:
                curlegend = legend[itrdata]

            if self._useNumpy:
                ax.plot(data['frq'] / scalef, trdata['data'], label = curlegend)
            else:
                frqs2 = []
                for f in data['frq']:
                    frqs2.append(f / scalef)
                ax.plot(frqs2, trdata['data'], label = curlegend)

        ax.set_xlabel(f"Frequency [{scaleprefix}Hz]")

        ax.grid()
#        if legend is not None or len(data['data']) > 1:
#            ax.legend()

        if title is not None:
            ax.title(title)


        # Quick FWHM and peakfinder for impedance match test
        import numpy as np
        minV, minVarg = np.min(data['data'][0]['data']), np.argmin(data['data'][0]['data'])
        ax.plot(data['frq'][minVarg] / scalef, minV, 'o', label = None)
        maxV = np.max(data['data'][0]['data'])
        hm = (maxV + minV) / 2.0
        xl, xr = minVarg, minVarg
        while data['data'][0]['data'][xl] < hm:
            xl = xl - 1
        while data['data'][0]['data'][xr] < hm:
            xr = xr + 1
        ax.plot([ data['frq'][xl] / scalef, data['frq'][xr] / scalef ], [ data['data'][0]['data'][xl], data['data'][0]['data'][xr] ], 'r--', label = f"FWHM {(data['frq'][xr] - data['frq'][xl]) / scalef} MHz")

        ax.legend()
        print(f"Minimum at {minV} dBm at {data['frq'][minVarg] / scalef} MHz")

        if show:
            plt.show()


    def _query_trace(self, traceidx = 0):
        traceData = []

        if not isinstance(traceidx, list) and not isinstance(traceidx, tuple):
            realTrace = traceidx + 1
            r = self._scpi.scpiQuery(f":TRAC:DATA? {realTrace}")
            data = r.split(",")[:-1]
            for i in range(len(data)):
                data[i] = float(data[i])
            traceData.append({ 'trace' : traceidx, 'data' : data})
        else:
            for tri in traceidx:
                realTrace = tri + 1
                r = self._scpi.scpiQuery(f":TRAC:DATA? {realTrace}")
                data = r.split(",")[:-1]
                for i in range(len(data)):
                    data[i] = float(data[i])
                traceData.append({ 'trace' : tri, 'data' : data })

        # Query frequency start stop and increment
        start = float(self._scpi.scpiQuery(":SENS:FREQ:STAR?"))
        stop = float(self._scpi.scpiQuery(":SENS:FREQ:STOP?"))
        steps = (stop - start) / (len(data) - 1)

        # ToDo: use numpy flag ...
        if self._useNumpy:
            import numpy as np
            frqs = np.linspace(start, stop+steps, len(data))
        else:
            frqs = []
            for i in range(len(data)):
                frqs.append(start + i * steps)

        return {
            'frq' : frqs,
            'data' : traceData
        }

    def _get_reference_level(self, powerunit = RFPowerLevel.dBm):
        if not isinstance(powerunit, RFPowerLevel):
            raise ValueError("Powerunit has to be an instance of POWERUNITS")

        r = float(self._scpi.scpiQuery(":DISP:WIND:TRAC:Y:RLEV?"))
        if powerunit == RFPowerLevel.dBm:
            return (r, RFPowerLevel.dBm, 'dBm')
        else:
            raise ValueError(f"Unsupported power unit {powerunit}")

    def _set_reference_level(self, power, powerunit = RFPowerLevel.dBm):
        # Convert to dBm
        if not isinstance(powerunit, RFPowerLevel):
            raise ValueError("Powerunit has to be an instance of POWERUNITS")

        pwr = None
        if powerunit == RFPowerLevel.dBm:
            pwr = power
        else:
            raise ValueError(f"Unsupported power unit {powerunit}")

        self._scpi.scpiCommand(f":DISP:WIND:TRAC:Y:RLEV {pwr} DBM")
        return True

    def _set_freq_range(self, start, stop):
        if stop < start:
            raise ValueError("Stop frequency has to be larger than start frequency")
        if start < 50:
            raise ValueError("Minimum frequency is 50 Hz")
        if (start > 3.2e9) or (stop > 3.2e9):
            raise ValueError("Maximum supported frequency is 3.2 GHz")
        self._scpi.scpiCommand(f":FREQ:STAR {start} Hz")
        self._scpi.scpiCommand(f":FREQ:STOP {stop} Hz")
        return True

if __name__ == "__main__":
    from time import sleep
    with SSA3021X("10.4.1.15", useNumpy = True) as ssa:
        print(ssa._id())
        #print(ssa._query_trace((0,1)))
        ssa._plot_trace(legend = "S11", show = True, scale=SISCALE.MEGA)
        #ssa._set_reference_level(0)
        #print(ssa._get_reference_level())
        #sleep(10)
        #ssa._set_reference_level(-5)
        #ssa._set_freq_range(202e6-5e6, 202e6+5e6)
