//#define F_CPU 16000000UL // CPU-Frequenz des ATmega328P (16 MHz)
#include <avr/io.h>
#include <avr/interrupt.h>
#include <unistd.h>
#include <signal.h>
#include <stdio.h>
#include <util/delay.h>
#include "errors.hpp"
#include "addresses.h"

// LED Pins
#define RED_LED_PIN PD6
#define BLUE_LED_PIN PD5
#define GREEN_LED_PIN PD7
#define YELLOW_LED_PIN PB0


//LIN Pins
#define RX_PIN PD0
#define TX_PIN PD1
#define CS_PIN PD2

const uint16_t BAUD = 19200;

void init(uint16_t baud)
{
  cli();

  
  // LED Init
  DDRD |= (1 << BLUE_LED_PIN); //OUT
  DDRD |= (1 << GREEN_LED_PIN); //OUT
  DDRD |= (1 << RED_LED_PIN); //OUT
  DDRB |= (1 << YELLOW_LED_PIN); //OUT



  // COM Pin Init
  DDRD &= ~(1 << RX_PIN); //IN
  DDRD |= (1 << TX_PIN); //OUT
  DDRD |= (1 << CS_PIN); //OUT
    
  PORTD |= (1 << CS_PIN); //HIGH



  /* uart init */
  uint16_t ubrr =  (((F_CPU / (baud * 16UL))) - 1);
  
  /*Set baud rate */
  UBRR0H = (uint8_t)(ubrr>>8);
  UBRR0L = (uint8_t)ubrr; 
  //UCSR0B |= (1 << RXCIE0);
  //Enable receiver and transmitter
  UCSR0B |= (1<<RXEN0) | (1<<TXEN0);
  /* Set frame format: 8data, 1stop bit */
  UCSR0C |= (1 << UCSZ01) | (1 << UCSZ00);

  /* adc init */

  PORTC &= ~(1 << PC2);  // kein Pullup 
  PORTC &= ~(1 << PC3);  // kein Pullup 
  DDRC  &= ~(1 << PC2);  // Input 
  DDRC  &= ~(1 << PC3);  // Input

  DIDR0 |= (1 << ADC2D) | (1 << ADC3D);


  ADMUX = (1<<REFS0);     //select AVCC as reference
  //ADSRA = (1<<ADEN) | 7;
  //enable and prescale = 128 (16MHz/128 = 125kHz)
  ADCSRA = (1 << ADEN) | (1 << ADPS2) | (1 << ADPS1) | (1 << ADPS0);

  sei();  ////Serial Interrupt enable
}

 
uint16_t readadc(uint8_t channel)
{
    ADMUX = (ADMUX & 0xf0) | (channel & 0x07);  //select input and ref

    ADCSRA |= (1 << ADSC);

    // Warten, bis ADSC wieder 0 ist (Konvertierung abgeschlossen)
    while (ADCSRA & (1 << ADSC));
    
    // Ergebnis zurckgeben (ADC ist das 16-bit Register)
    return ADC;
}


void portd(uint8_t pin, uint8_t value) {
  if (value) {
    PORTD |= (1 << pin);  // LED einschalten
  } else {
    PORTD &= ~(1 << pin); // LED ausschalten
  }
}

void portb(uint8_t pin, uint8_t value) {
  if (value) {
    PORTB |= (1 << pin);  // LED einschalten
  } else {
    PORTB &= ~(1 << pin); // LED ausschalten
  }
}

void error (int status) {
  int sts = 0;
  if (status < 0) {
    sts = -status;
  }

    portb(YELLOW_LED_PIN, 0);
    portd(RED_LED_PIN, 0);
    portd(GREEN_LED_PIN, 0);
    portd(BLUE_LED_PIN, 0);

  for (int i = 0; i < sts; i++) {
    portb(YELLOW_LED_PIN, 0);
    _delay_ms(100);
    portb(YELLOW_LED_PIN, 1);
    _delay_ms(100);    
  }
  portb(YELLOW_LED_PIN, 0);
  _delay_ms(100);
}

void transmitbyte(uint8_t data)
{

  while ( !( UCSR0A & (1<<UDRE0)) )
    ;

  UDR0 = data;
}




int receivebyte(void)
{
  // 1000 ist about 40 seconds
  // 250 is about 10 seconds
  for (unsigned int i = 0; i < 250; i++) {
    for (unsigned int j = 0; j < 0xFFF0; j++) {

      if (UCSR0A & (1<<RXC0)) {
	return UDR0;

      }
    }
  }

  return LIN_TIM_ERR;
  
}

void running(unsigned int n) {
  for (unsigned int i = 0; i < n; i++) {
    portb(YELLOW_LED_PIN, 1);
    portd(RED_LED_PIN, 0);
    portd(GREEN_LED_PIN, 0);
    portd(BLUE_LED_PIN, 0);
    _delay_ms(200);
    portb(YELLOW_LED_PIN, 0);
    portd(RED_LED_PIN, 1);
    portd(GREEN_LED_PIN, 0);
    portd(BLUE_LED_PIN, 0);
    _delay_ms(200);
    portb(YELLOW_LED_PIN, 0);
    portd(RED_LED_PIN, 0);
    portd(GREEN_LED_PIN, 1);
    portd(BLUE_LED_PIN, 0);
    _delay_ms(200);
    portb(YELLOW_LED_PIN, 0);
    portd(RED_LED_PIN, 0);
    portd(GREEN_LED_PIN, 0);
    portd(BLUE_LED_PIN, 1);
    _delay_ms(200);
  }
  portb(YELLOW_LED_PIN, 0);
  portd(RED_LED_PIN, 0);
  portd(GREEN_LED_PIN, 0);
  portd(BLUE_LED_PIN, 0);
  
}

void bar(uint16_t n) {

  uint16_t limit = 800; // approx 4*1023/5
  
  if (n < limit/5) {
    portb(YELLOW_LED_PIN, 0);
    portd(RED_LED_PIN, 0);
    portd(GREEN_LED_PIN, 0);
    portd(BLUE_LED_PIN, 0);
  } else if (n < 2*limit/5) {
    portb(YELLOW_LED_PIN, 1);
    portd(RED_LED_PIN, 0);
    portd(GREEN_LED_PIN, 0);
    portd(BLUE_LED_PIN, 0);
  } else if (n < 3*limit/5) {
    portb(YELLOW_LED_PIN, 1);
    portd(RED_LED_PIN, 1);
    portd(GREEN_LED_PIN, 0);
    portd(BLUE_LED_PIN, 0);
  } else if (n < 4*limit/5) {
    portb(YELLOW_LED_PIN, 1);
    portd(RED_LED_PIN, 1);
    portd(GREEN_LED_PIN, 1);
    portd(BLUE_LED_PIN, 0);
  } else {
    portb(YELLOW_LED_PIN, 1);
    portd(RED_LED_PIN, 1);
    portd(GREEN_LED_PIN, 1);
    portd(BLUE_LED_PIN, 1);
  }
  
}

uint8_t largest(uint16_t l[6]) {

  uint16_t max = l[0];
  uint8_t index = 0;

  for (uint8_t i = 1; i < 6; i++) {

    if (l[i] > max) {
      max = l[i];
      index = i;
    }
  }
  
  return index;
}


uint8_t checksum(const uint8_t *data, uint8_t data_size) {
  uint16_t check = 0;
  while (data_size-- > 0) {
    check += *(data++);
    if (check > 0xFF) {
      check -= 0xFF;
    }
  }

  return (~check) & 0xFF;
}




int main() {

  init(BAUD);

    //while(true) {
    //portb(YELLOW_LED_PIN, 1);
    //_delay_ms(500);
    //portb(YELLOW_LED_PIN, 0);
    //_delay_ms(500);
    //uint16_t val1 = readadc(2);
    //uint16_t val2 = readadc(3);
    
    //int sync = receivebyte();
    //if(sync==LIN_TIM_ERR) {
    //portb(YELLOW_LED_PIN, 1);
    //_delay_ms(100);
    //portb(YELLOW_LED_PIN, 0);
    //_delay_ms(100);
    //portb(YELLOW_LED_PIN, 1);
    //_delay_ms(100);
    //portb(YELLOW_LED_PIN, 0);
    //_delay_ms(100);
    //portb(YELLOW_LED_PIN, 1);
    //_delay_ms(100);
    //portb(YELLOW_LED_PIN, 0);
    //_delay_ms(100);
    //error(LIN_TIM_ERR);
    //}
  //}

/*  while(true) {
    running(1);
    uint16_t val1 = readadc(2);
    uint16_t val2 = readadc(3);
  }*/


  while(true) {
    /*portd(RED_LED_PIN, 1);
    _delay_ms(500);
    portd(RED_LED_PIN, 0);
    _delay_ms(500);*/
    int sync = receivebyte();
    if(sync==LIN_TIM_ERR){
      error(LIN_TIM_ERR);
    }
    if(sync!=0x55){
      continue;
    }
    int cntl = receivebyte();
    if((cntl&0x3f)== stslv1){
      uint16_t val1 = readadc(2);
      uint16_t val2 = readadc(3);
      //continue;
      uint8_t data[4];
      data[0] = val1 & 0xFF;
      data[1] = (val1 >> 8) & 0x03;
      data[2] = val2 & 0xFF;
      data[3] = (val2 >> 8) & 0x03;
      
      int check = 0;
      transmitbyte(data[0]);
      check = receivebyte();
      if (check != data[0]) {
	error(LIN_CHK_ERR);
	continue;
      }
      transmitbyte(data[1]);
      check = receivebyte();
      if (check != data[1]) {
	error(LIN_CHK_ERR);
	continue;
      }
      transmitbyte(data[2]);
      check = receivebyte();
      if (check != data[2]) {
	error(LIN_CHK_ERR);
	continue;
      }
      transmitbyte(data[3]);
      check = receivebyte();
      if (check != data[3]) {
	error(LIN_CHK_ERR);
	continue;
      }
      int checks = checksum(data, 4);
      transmitbyte(checks);
      check = receivebyte();
      if (check != checks) {
	error(LIN_CHK_ERR);
	continue;
      }
      continue;
    }
    else if((cntl&0x3f)== cntlslv0){
      uint8_t data[2];
      data[0] = receivebyte();
      data[1] = receivebyte();
      if(data[0] == 0x01 && data[1] == 0xab){
        portb(YELLOW_LED_PIN, 1);
        portd(RED_LED_PIN, 1);
        portd(GREEN_LED_PIN, 1);
        portd(BLUE_LED_PIN, 1);
      }
      if(data[0] == 0xcd && data[1] == 0x0c){
        portb(YELLOW_LED_PIN, 0);
        portd(RED_LED_PIN, 0);
        portd(GREEN_LED_PIN, 0);
        portd(BLUE_LED_PIN, 0);
      }
      
      int check = receivebyte();
      if (check != checksum(data,2)) {
	error(LIN_CHK_ERR);
      }
      continue;
    }   
    
  }

  /*
  while(true) {
    portb(YELLOW_LED_PIN, 1);
    portd(RED_LED_PIN, 1);
    portd(GREEN_LED_PIN, 1);
    portd(BLUE_LED_PIN, 1);
    
    _delay_ms(250);

    portb(YELLOW_LED_PIN, 0);
    portd(RED_LED_PIN, 0);
    portd(GREEN_LED_PIN, 0);
    portd(BLUE_LED_PIN, 0);
    

    _delay_ms(250);
  }
    */
  
  return(0);
}
