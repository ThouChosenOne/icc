from scapy.all import *
from icc.gsmpackets import *
from detector import Detector


class IDRequestDetector(Detector):

    def handle_packet(self, data):
        p = GSMTap(data)
        if p.payload.name is 'LAPDm':
            if p.payload.payload.name is 'GSMAIFDTAP':
                if p.payload.payload.payload.name is 'IdentityRequest':
                    id_type = p.payload.payload.payload.id_type
                    if id_type == 1:
                        print 'IMSI request detected'
                        self.counter += 1
                        self.update_rank(Detector.UNKNOWN, 'IMSI request detected %s times' % self.counter)

