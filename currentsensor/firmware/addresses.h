#ifndef ADDRESSES_H
#define ADDRESSES_H

const uint8_t cntlslv0 = 0x09;
const uint8_t cntlslv1 = 0x1a;
const uint8_t cntlslv2 = 0x2f;
const uint8_t cntlslv3 = 0x39;

const uint8_t stslv0 = 0x04;
const uint8_t stslv1 = 0x1b;
const uint8_t stslv2 = 0x2e;
const uint8_t stslv3 = 0x3a;

const uint8_t master = 0xff;
const uint8_t slave0 = 0x00;
const uint8_t slave1 = 0x01;
const uint8_t slave2 = 0x02;
const uint8_t slave3 = 0x03;


const uint8_t pids[] ={cntlslv0, cntlslv1, cntlslv2, stslv0, stslv1};
const uint8_t messagebytes[] ={2, 3, 4, 3, 4};

const uint8_t sources[] ={master, master,master, slave0, slave0};
const uint8_t destinations[] ={slave0, slave0, slave0,master, master};


  
#endif
