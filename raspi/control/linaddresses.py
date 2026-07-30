class constants:

    sync = 0x55
    
    cntlslv0 = 0x09
    cntlslv1 = 0x1a
    cntlslv2 = 0x2f
    cntlslv3 = 0x39

    stslv0 = 0x04
    stslv1 = 0x1b
    stslv2 = 0x2e
    stslv3 = 0x3a

    master = 0xff
    slave0 = 0x00
    slave1 = 0x01
    slave2 = 0x02
    slave3 = 0x03


    pids = [cntlslv0, cntlslv1, cntlslv2, cntlslv3, stslv0, stslv1, stslv2]
    messagebytes = [2, 2, 6, 2, 3, 2, 2]

    sources =[master, master, master, master, slave0, slave0, slave0]
    destinations = [slave0, slave0, slave0, slave0, master, master, master]

