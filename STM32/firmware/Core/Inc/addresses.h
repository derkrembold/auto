/* Generated from addresses.json by generate_addresses.py — do not edit directly.
 * Edit addresses.json and re-run the generator instead.
 */

#ifndef ADDRESSES_HPP
#define ADDRESSES_HPP

const uint8_t cntlslv0 = 0x09;
const uint8_t cntlslv1 = 0x1a;
const uint8_t cntlslv2 = 0x2f;
const uint8_t cntlslv3 = 0x39;
const uint8_t stslv0 = 0x04;
const uint8_t stslv1 = 0x1b;
const uint8_t stslv2 = 0x2e;

const uint8_t master = 0xff;
const uint8_t slave0 = 0x00;
const uint8_t slave1 = 0x01;
const uint8_t slave2 = 0x02;
const uint8_t slave3 = 0x03;


const uint8_t pids[] = {cntlslv0, cntlslv1, cntlslv2, cntlslv3, stslv0, stslv1, stslv2};
const uint8_t messagebytes[] = {2, 2, 6, 2, 3, 2, 2};

const uint8_t sources[] = {master, master, master, master, slave0, slave0, slave0};
const uint8_t destinations[] = {slave0, slave0, slave0, slave0, master, master, master};

#endif
