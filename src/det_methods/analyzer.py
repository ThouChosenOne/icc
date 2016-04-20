from gnuradio import blocks
from gnuradio import eng_notation
from gnuradio import gr
from gnuradio.eng_option import eng_option
from gnuradio.filter import firdes
from math import pi
from optparse import OptionParser

import grgsm
import osmosdr
import pmt
import signal
import sys



"""
Block that analyses a specific cell tower ARFCN for a specified amount of time.
Stores the capture in cfile format, and stores the bursts(frames)
Sends the decoded stuff to all ports in the udp port list
"""

class Analyzer(gr.top_block):

    def __init__(self, fc, gain, samp_rate, ppm, arfcn, capture_id, udp_ports=[], max_timeslot=0, store_capture=True, verbose=False, band=None, rec_length=None, test=False, args=""):
        """
        capture_id = identifier for the capture used to store the files (e.g. <capture_id>.cfile)
        store_capture = boolean indicating if the capture should be stored on disk or not
        rec_length = capture time in seconds
        max_timeslot = timeslot 0...max_timeslot will be decoded
        udp_ports = a list of udp ports to send the captured GSMTap frames to
        """

        gr.top_block.__init__(self, "Gr-gsm Capture")

        ##################################################
        # Parameters
        ##################################################
        self.fc = fc
        self.gain = gain
        self.samp_rate = samp_rate
        self.ppm = ppm
        self.arfcn = arfcn
        self.band = band
        self.shiftoff = shiftoff = 400e3
        self.rec_length = rec_length
        self.store_capture = store_capture
        self.capture_id = capture_id
        self.udp_ports = udp_ports
        self.verbose = verbose

        ##################################################
        # Processing Blocks
        ##################################################

        self.rtlsdr_source = osmosdr.source( args="numchan=" + str(1) + " " + "" )
        self.rtlsdr_source.set_sample_rate(samp_rate)
        self.rtlsdr_source.set_center_freq(fc - shiftoff, 0)
        self.rtlsdr_source.set_freq_corr(ppm, 0)
        self.rtlsdr_source.set_dc_offset_mode(2, 0)
        self.rtlsdr_source.set_iq_balance_mode(2, 0)
        self.rtlsdr_source.set_gain_mode(True, 0)
        self.rtlsdr_source.set_gain(gain, 0)
        self.rtlsdr_source.set_if_gain(20, 0)
        self.rtlsdr_source.set_bb_gain(20, 0)
        self.rtlsdr_source.set_antenna("", 0)
        self.rtlsdr_source.set_bandwidth(250e3+abs(shiftoff), 0)
        self.blocks_rotator = blocks.rotator_cc(-2*pi*shiftoff/samp_rate)

        #RUn for the specified amount of seconds or indefenitely
        if self.rec_length is not None:
            self.blocks_head_0 = blocks.head(gr.sizeof_gr_complex, int(samp_rate*rec_length))

        self.gsm_receiver = grgsm.receiver(4, ([self.arfcn]), ([]))
        self.gsm_input = grgsm.gsm_input(
            ppm=0,
            osr=4,
            fc=fc,
            samp_rate_in=samp_rate,
        )
        self.gsm_clock_offset_control = grgsm.clock_offset_control(fc-shiftoff)

        #Control channel demapper for timeslot 0
        self.gsm_bcch_ccch_demapper_0 = grgsm.universal_ctrl_chans_demapper(0, ([2,6,12,16,22,26,32,36,42,46]), ([1,2,2,2,2,2,2,2,2,2]))
        #For all other timeslots are assumed to contain sdcch8 logical channels, this demapping may be incorrect
        if max_timeslot >= 1 and max_timeslot <= 8:
            self.gsm_sdcch8_demappers = []
            for i in range(1,max_timeslot + 1):
                self.gsm_sdcch8_demappers.append(grgsm.universal_ctrl_chans_demapper(i, ([0,4,8,12,16,20,24,28,32,36,40,44]), ([8,8,8,8,8,8,8,8,136,136,136,136])))

        #Control channel decoder (extracts the packets), one for each timeslot
        self.gsm_control_channels_decoders = []
        for i in range(0,max_timeslot + 1):
            self.gsm_control_channels_decoders.append(grgsm.control_channels_decoder())
#        self.blocks_socket_pdu_0 = blocks.socket_pdu("UDP_CLIENT", "127.0.0.1", "4729", 10000, False)#        self.blocks_socket_pdu_0 = blocks.socket_pdu("UDP_CLIENT", "127.0.0.1", "4729", 10000, False)

        #UDP client that sends all decoded C0T0 packets to the specified port on localhost if requested
        self.client_sockets = []
        self.server_sockets = []
        for udp_port in self.udp_ports:
            #The server is for testing only
            #WARNING remove the server if you want connect to a different one
            if test:
                self.server_sockets.append(blocks.socket_pdu("UDP_SERVER", "127.0.0.1", str(udp_port), 10000))
            self.client_sockets.append(blocks.socket_pdu("UDP_CLIENT", "127.0.0.1", str(udp_port), 10000))

        #Sinks to store the capture file if requested
        if self.store_capture:
            self.gsm_burst_file_sink = grgsm.burst_file_sink(str(self.capture_id) + ".burstfile")
            self.blocks_file_sink = blocks.file_sink(gr.sizeof_gr_complex*1, str(self.capture_id) + ".cfile", False)
            self.blocks_file_sink.set_unbuffered(False)

        #Printer for printing messages when verbose flag is True
        if self.verbose:
            self.gsm_message_printer = grgsm.message_printer(pmt.intern(""), False)

        """
        if self.verbose:
            self.gsm_bursts_printer_0 = grgsm.bursts_printer(pmt.intern(""),
                                                             False, False, False, False)
        """
        ##################################################
        # Connections
        ##################################################

        if self.rec_length is not None: #if recording length is defined connect head block after the source
            self.connect((self.rtlsdr_source, 0), (self.blocks_head_0, 0))
            self.connect((self.blocks_head_0, 0), (self.blocks_rotator, 0))
        else:
            self.connect((self.rtlsdr_source, 0), (self.blocks_rotator, 0))

        #Connect the file sinks
        if self.store_capture:
            self.connect((self.blocks_rotator, 0), (self.blocks_file_sink, 0))
            self.msg_connect(self.gsm_receiver, "C0", self.gsm_burst_file_sink, "in")

        #Connect the GSM receiver
        self.connect((self.gsm_input, 0), (self.gsm_receiver, 0))
        self.connect((self.blocks_rotator, 0), (self.gsm_input, 0))
        self.msg_connect(self.gsm_clock_offset_control, "ppm", self.gsm_input, "ppm_in")
        self.msg_connect(self.gsm_receiver, "measurements", self.gsm_clock_offset_control, "measurements")

        #Connect the demapper and decoder for timeslot 0
        self.msg_connect((self.gsm_receiver, 'C0'), (self.gsm_bcch_ccch_demapper_0, 'bursts'))
        self.msg_connect((self.gsm_bcch_ccch_demapper_0, 'bursts'), (self.gsm_control_channels_decoders[0], 'bursts'))

        #Connect the demapper and decoders for the other timeslots
        for i in range(1,max_timeslot +1):
            self.msg_connect((self.gsm_receiver, 'C0'), (self.gsm_sdcch8_demappers[i-1], 'bursts'))
            self.msg_connect((self.gsm_sdcch8_demappers[i-1], 'bursts'), (self.gsm_control_channels_decoders[i], 'bursts'))


        #Connect the UDP clients if requested
        for client_socket in self.client_sockets:
            for i in range(0,max_timeslot + 1):
                self.msg_connect((self.gsm_control_channels_decoders[i], 'msgs'), (client_socket, 'pdus'))

        #Connect the printer is self.verbose is True
        if self.verbose:
            for i in range(0,max_timeslot + 1):
                self.msg_connect((self.gsm_control_channels_decoders[i], 'msgs'), (self.gsm_message_printer, 'msgs'))

        """
        if self.verbose:
            self.msg_connect(self.gsm_receiver, "C0", self.gsm_bursts_printer_0, "bursts")
        """



    def get_fc(self):
        return self.fc

    def set_fc(self, fc):
        self.fc = fc
        if self.verbose or self.burst_file:
            self.gsm_input.set_fc(self.fc)

    def get_arfcn(self):
        return self.arfcn

    def set_arfcn(self, arfcn):
        self.arfcn = arfcn
        if self.verbose or self.burst_file:
            self.gsm_receiver.set_cell_allocation([self.arfcn])
            if options.band:
                new_freq = grgsm.arfcn.arfcn2downlink(self.arfcn, self.band)
            else:
                for band in grgsm.arfcn.get_bands():
                    if grgsm.arfcn.is_valid_arfcn(arfcn, band):
                        new_freq = grgsm.arfcn.arfcn2downlink(arfcn, band)
                        break
            self.set_fc(new_freq)

    def get_gain(self):
        return self.gain

    def set_gain(self, gain):
        self.gain = gain

    def get_samp_rate(self):
        return self.samp_rate

    def set_samp_rate(self, samp_rate):
        self.samp_rate = samp_rate
        self.rtlsdr_source.set_sample_rate(self.samp_rate)
        if self.verbose or self.burst_file:
            self.gsm_input.set_samp_rate_in(self.samp_rate)

    def get_ppm(self):
        return self.ppm

    def set_ppm(self, ppm):
        self.ppm = ppm
        self.set_ppm_slider(self.ppm)

    def get_rec_length(self):
        return self.rec_length

    def set_rec_length(self, rec_length):
        self.rec_length = rec_length
        self.blocks_head_0.set_length(int(self.samp_rate*self.rec_length))


if __name__ == '__main__':

    arfcn = 0
    fc = 933.6e6 #Spiegel cell tower
    sample_rate = 2000000.052982
    ppm = 90 #frequency offset in ppm
    gain = 30


    #Get the arfcn
    for band in grgsm.arfcn.get_bands():
        if grgsm.arfcn.is_valid_downlink(fc, band):
            arfcn = grgsm.arfcn.downlink2arfcn(fc, band)
            break

    print("ARFCN: " + str(arfcn))

    analyzer = Analyzer(fc=fc, gain=gain, samp_rate=sample_rate,
                        ppm=ppm, arfcn=arfcn, capture_id="test0",
                        udp_ports=[4729], rec_length=30, max_timeslot=2,
                        verbose=True, test=True)
    analyzer.start()
    analyzer.wait()

    #Commandline parsing
    """
    parser = OptionParser(option_class=eng_option, usage="%prog [options]",
                          description="RTL-SDR capturing app of gr-gsm.")

    parser.add_option("-f", "--fc", dest="fc", type="eng_float",
                      help="Set frequency [default=%default]")

    parser.add_option("-a", "--arfcn", dest="arfcn", type="intx",
                      help="Set ARFCN instead of frequency. In some cases you may have to provide the GSM band also")

    parser.add_option("-g", "--gain", dest="gain", type="eng_float",
                      default=eng_notation.num_to_str(30),
                      help="Set gain [default=%default]")

    parser.add_option("-s", "--samp-rate", dest="samp_rate", type="eng_float",
                      default=eng_notation.num_to_str(2000000.052982),
                      help="Set samp_rate [default=%default]")

    parser.add_option("-p", "--ppm", dest="ppm", type="intx", default=0,
                      help="Set ppm [default=%default]")

    parser.add_option("-b", "--burst-file", dest="burst_file",
                      help="File where the captured bursts are saved")

    parser.add_option("-c", "--cfile", dest="cfile",
                      help="File where the captured data are saved")

    bands_list = ", ".join(grgsm.arfcn.get_bands())
    parser.add_option("--band", dest="band",
                      help="Specify the GSM band for the frequency.\nAvailable bands are: " + bands_list + ".\nIf no band is specified, it will be determined automatically, defaulting to 0." )

    parser.add_option("", "--args", dest="args", type="string", default="",
        help="Set device arguments [default=%default]")

    parser.add_option("-v", "--verbose", action="store_true",
                      help="If set, the captured bursts are printed to stdout")

    parser.add_option("-T", "--rec-length", dest="rec_length", type="eng_float",
        help="Set length of recording in seconds [default=%default]")

    (options, args) = parser.parse_args()

    if options.cfile is None and options.burst_file is None:
        parser.error("Please provide a cfile or a burst file (or both) to save the captured data\n")

    if (options.fc is None and options.arfcn is None) or (options.fc is not None and options.arfcn is not None):
        parser.error("You have to provide either a frequency or an ARFCN (but not both).\n")

    arfcn = 0
    fc = 939.4e6
    if options.arfcn:
        if options.band:
            if options.band not in grgsm.arfcn.get_bands():
                parser.error("Invalid GSM band\n")
            elif not grgsm.arfcn.is_valid_arfcn(options.arfcn, options.band):
                parser.error("ARFCN is not valid in the specified band\n")
            else:
                arfcn = options.arfcn
                fc = grgsm.arfcn.arfcn2downlink(arfcn, options.band)
        else:
            arfcn = options.arfcn
            for band in grgsm.arfcn.get_bands():
                if grgsm.arfcn.is_valid_arfcn(arfcn, band):
                    fc = grgsm.arfcn.arfcn2downlink(arfcn, band)
                    break
    elif options.fc:
        fc = options.fc
        if options.band:
            if options.band not in grgsm.arfcn.get_bands():
                parser.error("Invalid GSM band\n")
            elif not grgsm.arfcn.is_valid_downlink(options.fc, options.band):
                parser.error("Frequency is not valid in the specified band\n")
            else:
                arfcn = grgsm.arfcn.downlink2arfcn(options.fc, options.band)
        else:
            for band in grgsm.arfcn.get_bands():
                if grgsm.arfcn.is_valid_downlink(options.fc, band):
                    arfcn = grgsm.arfcn.downlink2arfcn(options.fc, band)
                    break

    tb = grgsm_capture(fc=fc, gain=options.gain, samp_rate=options.samp_rate,
                         ppm=options.ppm, arfcn=arfcn, cfile=options.cfile,
                         burst_file=options.burst_file, band=options.band, verbose=options.verbose,
                         rec_length=options.rec_length)

    def signal_handler(signal, frame):
        tb.stop()
        tb.wait()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    tb.start()
    tb.wait()
    """
