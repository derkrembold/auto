/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2025 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include "addresses.h"
#include "errors.h"
#include "main.h"
//#include "lin.hpp"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */
#define BIT(addr, num) ((addr >> num) & 0x01)
/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
ADC_HandleTypeDef hadc2;
TIM_HandleTypeDef htim4;
TIM_HandleTypeDef htim5;
UART_HandleTypeDef huart4;



/* USER CODE BEGIN PV */

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MPU_Config(void);
static void MX_GPIO_Init(void);
static void MX_UART4_Init(void);
static void MX_ADC2_Init(void);
static void MX_TIM4_Init(void);
static void MX_TIM5_Init(void);
/* USER CODE BEGIN PFP */
uint8_t checksum(const uint8_t *, uint8_t);
void delay_ms(uint16_t);
void delay_us(uint32_t);
void fillbody(uint8_t, uint8_t*, uint8_t);
void error (int);
void updateramp(void);
uint8_t iam();
uint8_t addparity(uint8_t);
int8_t getindex(uint8_t);

void allOff();                 // Schaltet alle MOSFET-Ausgaenge aus (Motor stromlos)
void driveMOSFET(int, GPIO_PinState);
void driveState(uint16_t speed, int);
uint8_t driveStep(int16_t);
int16_t picontrol(int16_t setpoint, int16_t processvalue);


/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

uint8_t rx_header[2];
uint8_t rx_body[10];

uint8_t linbodysize = 0;
uint8_t tx_body[10];


volatile bool headerrecvd = false;
volatile bool bodyrecvd = false;
volatile bool bodysent = false;
volatile uint32_t bodyWaitStartTick = 0;
volatile bool bodyTimedOut = false;
volatile uint16_t bodyTimeoutCount = 0;
volatile uint16_t checksumErrorCount = 0;
#define LIN_BODY_TIMEOUT_MS 50



// eine konstante mit 8-Bit-Ganzzahl, Ã¤ndert sich nie
// hier die drei hallsensoren des bdlc's motors
// arduino liest sie aus, um die aktuelle Rotorposition zu bestimmen
// Hallsensoren liefern Muster wie 101, 100, 110, etc
const uint8_t H1_PIN = 11;
const uint8_t H2_PIN = 12;
const uint8_t H3_PIN = 13;

// Jede Phase A/B/C hat ein High-Side MOSFET (H)und ein Low Side MOSFET (L)
const uint8_t AH = 0;
const uint8_t AL = 1;
const uint8_t BH = 2;
const uint8_t BL = 3;
const uint8_t CH = 4;
const uint8_t CL = 5;


const uint32_t GLOBALRATE = 1275; // in mikrosekunden
//const int16_t MINCONTROLVARIABLE = 200; //
const uint32_t RAMPSTEP = 1;
const float CONTROLLIMIT = GLOBALRATE - 100;
const float KP = 0.15f;
const float KI = 0.4f;


// RPMFACTOR: 60*speedcount/(24*0.1); 60sec/min; 24steps/Umdrehung; 0.1s==100ms;
const uint16_t RPMFACTOR = 25;
const uint16_t SAMPLERATE = 100; // in ms
const float DT = GLOBALRATE / 1000000.0f;  // in seconds

int16_t controlvariable = 0;
int16_t controlvariableinput = 0;

//Sollwert = setpoint
//Istwert = actual value (oder process value)
//Führungsgröße = reference variable (oder command variable)

int16_t rpm = 0;
float integral = 0.0f;
uint8_t hwbits = 0x0;

volatile const int directionMatrix[6][6] = {
		{0, 1, 2, 0, -2, -1}, // 1 -> Sprung zu 2=CW, 3=CCW, 5=CW, 6=CCW
		{-1, 0, 1, 2, 0, -2}, // 2
		{-2,-1, 0, 1, 2, 0}, // 3
		{0, -2,-1, 0, 1, 2}, // 4
		{2, 0, -2,-1, 0, 1}, // 5
		{1, 2, 0, -2,-1, 0}  // 6
};

volatile uint8_t previousState = 0;
volatile int32_t hallCounter = 0;

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MPU Configuration--------------------------------------------------------*/
  MPU_Config();

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_UART4_Init();
  MX_ADC2_Init();
  MX_TIM4_Init();
  MX_TIM5_Init();
  /* USER CODE BEGIN 2 */
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_4, GPIO_PIN_SET); // CS on high
  /* USER CODE END 2 */



  /* Infinite loop */
  /* USER CODE BEGIN WHILE */



  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_7, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_9, GPIO_PIN_RESET);

  HAL_GPIO_WritePin(GPIOE, GPIO_PIN_8, GPIO_PIN_RESET);// lower board low, LINA, arduino digital 8
  HAL_GPIO_WritePin(GPIOE, GPIO_PIN_9, GPIO_PIN_RESET);// lower board high, HINA, arduino digital 6
  HAL_GPIO_WritePin(GPIOE, GPIO_PIN_10, GPIO_PIN_RESET);// middle board low, LINB, arduino digiial 5
  HAL_GPIO_WritePin(GPIOE, GPIO_PIN_11, GPIO_PIN_RESET);// middle board high, HINB, arduino digital 4
  HAL_GPIO_WritePin(GPIOE, GPIO_PIN_12, GPIO_PIN_RESET); // upper board low, LINC,, arduino digital 3
  HAL_GPIO_WritePin(GPIOE, GPIO_PIN_13, GPIO_PIN_RESET); // upper board high, HINC, arduino digital 2

  //Inputs
  // low, arduino digital 11
  // middle, arduino digital 12
  // high, arduino digital 13

  //__HAL_TIM_SET_COUNTER(&htim5,0);
  if(HAL_GPIO_ReadPin (GPIOB, GPIO_PIN_14) ==  GPIO_PIN_SET) {
    hwbits |= 0x01;
  } 
  if(HAL_GPIO_ReadPin (GPIOB, GPIO_PIN_15) ==  GPIO_PIN_SET) {
    hwbits |= 0x02;
  }
  
  driveStep(0);
  previousState = getState();

  int done = 1;

  for (;;)
  {
	  HAL_UART_Receive_IT(&huart4, rx_header, 2);
	  //HAL_UART_Transmit_IT(&huart4, tx_buff, 10);
	  //HAL_Delay(5000);
	  while (bodyrecvd == false) {

		  if (done == 1) {
			  __HAL_TIM_SET_COUNTER(&htim4, 0);  // reset counter
			  HAL_TIM_Base_Start(&htim4); // Start the timer
			  done = 0;
		  }

		  if (headerrecvd == true && (HAL_GetTick() - bodyWaitStartTick) > LIN_BODY_TIMEOUT_MS) {
			  HAL_UART_AbortReceive(&huart4);  // blockierend, kein DMA im Spiel -> praktisch sofort
			  headerrecvd = false;
			  bodyTimedOut = true;
			  bodyrecvd = true;  // bricht die while-Schleife ab
			  bodyTimeoutCount++;
		  }

		  if(HAL_GPIO_ReadPin (GPIOE, GPIO_PIN_5) ==  GPIO_PIN_RESET)
		  {
			  // Set The LED ON!
			  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, GPIO_PIN_SET);
			  //HAL_GPIO_WritePin(GPIOB, GPIO_PIN_12, GPIO_PIN_SET);
			  //HAL_GPIO_WritePin(GPIOE, GPIO_PIN_13, GPIO_PIN_SET);
			  //HAL_GPIO_WritePin(GPIOE, GPIO_PIN_11, GPIO_PIN_SET);
			  //HAL_GPIO_WritePin(GPIOE, GPIO_PIN_9, GPIO_PIN_SET);
		  }
		  else
		  {
			  // Else .. Turn LED OFF!
			  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, GPIO_PIN_RESET);
			  //HAL_GPIO_WritePin(GPIOB, GPIO_PIN_12, GPIO_PIN_RESET);
			  //HAL_GPIO_WritePin(GPIOE, GPIO_PIN_13, GPIO_PIN_RESET);
			  //HAL_GPIO_WritePin(GPIOE, GPIO_PIN_11, GPIO_PIN_RESET);
			  //HAL_GPIO_WritePin(GPIOE, GPIO_PIN_9, GPIO_PIN_RESET);
		  }
		  if(HAL_GPIO_ReadPin (GPIOC, GPIO_PIN_5) ==  GPIO_PIN_RESET)
		  {
			  // Set The LED ON!
			  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_7, GPIO_PIN_SET);
			  //HAL_GPIO_WritePin(GPIOE, GPIO_PIN_12, GPIO_PIN_SET);
			  //HAL_GPIO_WritePin(GPIOE, GPIO_PIN_10, GPIO_PIN_SET);
			  //HAL_GPIO_WritePin(GPIOE, GPIO_PIN_8, GPIO_PIN_SET);
		  }
		  else
		  {
			  // Else .. Turn LED OFF!
			  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_7, GPIO_PIN_RESET);
			  //HAL_GPIO_WritePin(GPIOE, GPIO_PIN_12, GPIO_PIN_RESET);
			  //HAL_GPIO_WritePin(GPIOE, GPIO_PIN_10, GPIO_PIN_RESET);
			  //HAL_GPIO_WritePin(GPIOE, GPIO_PIN_8, GPIO_PIN_RESET);
		  }
		  updateramp();
		  //picontrol(controlvariable, rpm);
		  //driveStep(controlvariable);

		  driveStep(picontrol(controlvariable, rpm));

	    if (__HAL_TIM_GET_COUNTER(&htim4) > SAMPLERATE) {
	    	HAL_TIM_Base_Stop(&htim4); // Stop the timer
	    	done = 1;
	    	rpm = RPMFACTOR*hallCounter;
	    	hallCounter = 0;
	    }
	  }
	  // some LIN message was received.
	  bodyrecvd = false;
	  if (bodyTimedOut) {
		  bodyTimedOut = false;
		  continue;  // Body nie angekommen -> verwerfen, neu auf Sync-Byte warten
	  }

	  bool checksum_ok = (checksum(rx_body, linbodysize) == rx_body[linbodysize]);

	  bool is_our_write = ((rx_header[1]&0x3f) == (cntl0mot | hwbits))
	    || ((rx_header[1]&0x3f) == (cntl1mot | hwbits))
	    || ((rx_header[1]&0x3f) == (cntl2mot | hwbits))
	    || ((rx_header[1]&0x3f) == (cntl3mot | hwbits));
	  if (is_our_write && !checksum_ok) {
	    checksumErrorCount++;
	  }
	
	  if (checksum_ok && (rx_header[1]&0x3f) == (cntl0mot | hwbits) && rx_body[0] == 0x01 && rx_body[1] == 0xdb) {
		  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_9, GPIO_PIN_SET);
	  }
	  if (checksum_ok && (rx_header[1]&0x3f) == (cntl0mot | hwbits) && rx_body[0] == 0xcd && rx_body[1] == 0x0c) {
		  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_9, GPIO_PIN_RESET);
	  }
	  if (checksum_ok && (rx_header[1]&0x3f) == (cntl1mot | hwbits)) {
		  int16_t speedlocal = (int16_t)((rx_body[0] << 8) | rx_body[1]);
		  driveStep(speedlocal);
		  driveStep(0);
		  driveStep(0);
		  driveStep(speedlocal);
		  driveStep(0);
		  driveStep(0);
		  driveStep(speedlocal);
		  driveStep(0);
		  driveStep(0);
	  }
	  if (checksum_ok && (rx_header[1]&0x3f) == (cntl2mot | hwbits)) {
		  driveMOSFET(AL, rx_body[0] == 1 ? GPIO_PIN_SET : GPIO_PIN_RESET);
		  driveMOSFET(AH, rx_body[1] == 1 ? GPIO_PIN_SET : GPIO_PIN_RESET);
		  driveMOSFET(BL, rx_body[2] == 1 ? GPIO_PIN_SET : GPIO_PIN_RESET);
		  driveMOSFET(BH, rx_body[3] == 1 ? GPIO_PIN_SET : GPIO_PIN_RESET);
		  driveMOSFET(CL, rx_body[4] == 1 ? GPIO_PIN_SET : GPIO_PIN_RESET);
		  driveMOSFET(CH, rx_body[5] == 1 ? GPIO_PIN_SET : GPIO_PIN_RESET);
	  }
	  if (checksum_ok && (rx_header[1]&0x3f) == (cntl3mot | hwbits)) {
		  controlvariableinput = (int16_t)((rx_body[0] << 8) | rx_body[1]);
		  if (controlvariableinput == 0) {
		    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_12, GPIO_PIN_RESET);
		  } else {
		    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_12, GPIO_PIN_SET);
		  }
	  }
  }


}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Supply configuration update enable
  */
  HAL_PWREx_ConfigSupply(PWR_LDO_SUPPLY);

  /** Configure the main internal regulator output voltage
  */
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE3);

  while(!__HAL_PWR_GET_FLAG(PWR_FLAG_VOSRDY)) {}

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_DIV1;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_NONE;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2
                              |RCC_CLOCKTYPE_D3PCLK1|RCC_CLOCKTYPE_D1PCLK1;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
  RCC_ClkInitStruct.SYSCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB3CLKDivider = RCC_APB3_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_APB1_DIV2;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_APB2_DIV1;
  RCC_ClkInitStruct.APB4CLKDivider = RCC_APB4_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_1) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief UART4 Initialization Function
  * @param None
  * @retval None
  */
static void MX_UART4_Init(void)
{

  /* USER CODE BEGIN UART4_Init 0 */

  /* USER CODE END UART4_Init 0 */

  /* USER CODE BEGIN UART4_Init 1 */

  /* USER CODE END UART4_Init 1 */
  huart4.Instance = UART4;
  huart4.Init.BaudRate = 19200;
  huart4.Init.WordLength = UART_WORDLENGTH_8B;
  //huart4.Init.StartBits = UART_STARTBITS_0;
  huart4.Init.StopBits = UART_STOPBITS_1;
  huart4.Init.Parity = UART_PARITY_NONE;
  huart4.Init.Mode = UART_MODE_TX_RX;
  huart4.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart4.Init.OverSampling = UART_OVERSAMPLING_16;
  huart4.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
  huart4.Init.ClockPrescaler = UART_PRESCALER_DIV1;
  huart4.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
  if (HAL_UART_Init(&huart4) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_SetTxFifoThreshold(&huart4, UART_TXFIFO_THRESHOLD_1_8) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_SetRxFifoThreshold(&huart4, UART_RXFIFO_THRESHOLD_1_8) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_DisableFifoMode(&huart4) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN UART4_Init 2 */

  /* USER CODE END UART4_Init 2 */

}

/**
  * @brief ADC2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_ADC2_Init(void)
{

  /* USER CODE BEGIN ADC2_Init 0 */

  /* USER CODE END ADC2_Init 0 */

  ADC_ChannelConfTypeDef sConfig = {0};

  /* USER CODE BEGIN ADC2_Init 1 */

  /* USER CODE END ADC2_Init 1 */

  /** Common config
  */
  hadc2.Instance = ADC2;
  hadc2.Init.ClockPrescaler = ADC_CLOCK_ASYNC_DIV2;
  hadc2.Init.Resolution = ADC_RESOLUTION_12B;
  hadc2.Init.ScanConvMode = ADC_SCAN_DISABLE;
  hadc2.Init.EOCSelection = ADC_EOC_SINGLE_CONV;
  hadc2.Init.LowPowerAutoWait = DISABLE;
  hadc2.Init.ContinuousConvMode = DISABLE;
  hadc2.Init.NbrOfConversion = 1;
  hadc2.Init.DiscontinuousConvMode = DISABLE;
  hadc2.Init.ExternalTrigConv = ADC_SOFTWARE_START;
  hadc2.Init.ExternalTrigConvEdge = ADC_EXTERNALTRIGCONVEDGE_NONE;
  hadc2.Init.ConversionDataManagement = ADC_CONVERSIONDATA_DR;
  hadc2.Init.Overrun = ADC_OVR_DATA_PRESERVED;
  hadc2.Init.LeftBitShift = ADC_LEFTBITSHIFT_NONE;
  hadc2.Init.OversamplingMode = DISABLE;
  hadc2.Init.Oversampling.Ratio = 1;
  if (HAL_ADC_Init(&hadc2) != HAL_OK)
  {
    Error_Handler();
  }

  /** Configure Regular Channel
  */
  sConfig.Channel = ADC_CHANNEL_9;
  sConfig.Rank = ADC_REGULAR_RANK_1;
  sConfig.SamplingTime = ADC_SAMPLETIME_1CYCLE_5;
  sConfig.SingleDiff = ADC_SINGLE_ENDED;
  sConfig.OffsetNumber = ADC_OFFSET_NONE;
  sConfig.Offset = 0;
  sConfig.OffsetSignedSaturation = DISABLE;
  if (HAL_ADC_ConfigChannel(&hadc2, &sConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN ADC2_Init 2 */

  /* USER CODE END ADC2_Init 2 */

}

/**
  * @brief TIM4 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM4_Init(void)
{

  /* USER CODE BEGIN TIM4_Init 0 */

  /* USER CODE END TIM4_Init 0 */

  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM4_Init 1 */

  /* USER CODE END TIM4_Init 1 */
  htim4.Instance = TIM4;
  htim4.Init.Prescaler = 63999; // 65534
  htim4.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim4.Init.Period = 65535;
  htim4.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim4.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_Base_Init(&htim4) != HAL_OK)
  {
    Error_Handler();
  }
  sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
  if (HAL_TIM_ConfigClockSource(&htim4, &sClockSourceConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim4, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }

}


/**
  * @brief TIM5 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM5_Init(void)
{

  /* USER CODE BEGIN TIM5_Init 0 */

  /* USER CODE END TIM5_Init 0 */

  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM5_Init 1 */

  /* USER CODE END TIM5_Init 1 */
  htim5.Instance = TIM5;
  htim5.Init.Prescaler = 64-1; //mit 70 war der Test ziemlich gut. Aber ich stelle trotzdem 64 sein.
  //htim5.Init.Prescaler = (HAL_RCC_GetPCLK1Freq() / 1000000) - 1;
  htim5.Init.CounterMode = TIM_COUNTERMODE_UP;
  //htim5.Init.Period = 999;
  htim5.Init.Period = 4294967295;
  htim5.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim5.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_Base_Init(&htim5) != HAL_OK)
  {
    Error_Handler();
  }
  sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
  if (HAL_TIM_ConfigClockSource(&htim5, &sClockSourceConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim5, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM5_Init 2 */
  //if (HAL_TIM_Base_Start_IT(&htim5) != HAL_OK)
  //{
    /* Starting Error */
    //Error_Handler();
  //}
  //HAL_TIM_Base_Start_IT(&htim5);
  /* USER CODE END TIM5_Init 2 */

}

static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  /* USER CODE BEGIN MX_GPIO_Init_1 */

  /* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOE_CLK_ENABLE();
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOE, GPIO_PIN_8|GPIO_PIN_9|GPIO_PIN_10|GPIO_PIN_11
                          |GPIO_PIN_12|GPIO_PIN_13, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_4|GPIO_PIN_6|GPIO_PIN_7|GPIO_PIN_8
                          |GPIO_PIN_9|GPIO_PIN_12, GPIO_PIN_RESET);


  /*Configure GPIO pin : PE5 */
  GPIO_InitStruct.Pin = GPIO_PIN_5;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(GPIOE, &GPIO_InitStruct);

  /*Configure GPIO pins : PC0 PC1 PC2 */
  GPIO_InitStruct.Pin = GPIO_PIN_0|GPIO_PIN_1|GPIO_PIN_2;
  //GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_RISING_FALLING;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOC, &GPIO_InitStruct);

  /*Configure GPIO pin : PC5 */
  GPIO_InitStruct.Pin = GPIO_PIN_5;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(GPIOC, &GPIO_InitStruct);

  /*Configure GPIO pin : PB0 */
  GPIO_InitStruct.Pin = GPIO_PIN_0;
  GPIO_InitStruct.Mode = GPIO_MODE_ANALOG;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pins : PE8 PE9 PE10 PE11
                           PE12 PE13 */
  GPIO_InitStruct.Pin = GPIO_PIN_8|GPIO_PIN_9|GPIO_PIN_10|GPIO_PIN_11
                          |GPIO_PIN_12|GPIO_PIN_13;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOE, &GPIO_InitStruct);

  /*Configure GPIO pins : PB4 PB6 PB7 PB8
                           PB9 PB12*/
  GPIO_InitStruct.Pin = GPIO_PIN_4|GPIO_PIN_6|GPIO_PIN_7|GPIO_PIN_8
                          |GPIO_PIN_9|GPIO_PIN_12;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pin : PB5 */
  GPIO_InitStruct.Pin = GPIO_PIN_5;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);


  /*Configure GPIO pin : PB14, PB15 */
  GPIO_InitStruct.Pin = GPIO_PIN_14 | GPIO_PIN_15;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);


  /* USER CODE BEGIN MX_GPIO_Init_2 */
  HAL_NVIC_SetPriority(EXTI0_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(EXTI0_IRQn);

  HAL_NVIC_SetPriority(EXTI1_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(EXTI1_IRQn);

  HAL_NVIC_SetPriority(EXTI2_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(EXTI2_IRQn);
  /* USER CODE END MX_GPIO_Init_2 */
}



/* USER CODE BEGIN 4 */
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
	//messagerecvd = false;
	if (headerrecvd == false && bodyrecvd == false) {
		if (rx_header[0] == 0x55) {
			uint8_t address = rx_header[1] & 0x3c;
			int8_t linindex = getindex(address);
			if (linindex >= 0) {
				if (pids[linindex] == address) {
				  if (sources[linindex] == master) {
				    linbodysize = messagebytes[linindex];
				    HAL_UART_Receive_IT(&huart4, rx_body, linbodysize + 1);
				    bodyWaitStartTick = HAL_GetTick();
				    headerrecvd = true;
				  } else if ((sources[linindex] == motor) && ((rx_header[1]&0x03) == hwbits)) {
				    linbodysize = messagebytes[linindex];
				    fillbody(rx_header[1]&0x3c, tx_body, linbodysize);
				    tx_body[linbodysize] = checksum(tx_body, linbodysize);
				    HAL_UART_Receive_IT(&huart4, rx_body, linbodysize + 1);
				    bodyWaitStartTick = HAL_GetTick();
				    HAL_UART_Transmit_IT(&huart4, tx_body, linbodysize + 1);

				    headerrecvd = true;
				    bodysent = true;
				  } else {
				    linbodysize = messagebytes[linindex];
				    HAL_UART_Receive_IT(&huart4, rx_body, linbodysize + 1);
				    bodyWaitStartTick = HAL_GetTick();
				    headerrecvd = true;
				    bodysent = false;
				  }
				}
			}
		}
	} else if(headerrecvd == true && bodyrecvd == false) {
		headerrecvd = false;
		bodyrecvd = true;
	} else if(bodysent == true) {
		bodysent = false;
	}

}


void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim){
	HAL_GPIO_TogglePin(GPIOB, GPIO_PIN_9);
}

int16_t picontrol(int16_t setpoint, int16_t processvalue)
{

    if(setpoint == 0)
    {
        integral = 0.0f;
        return 0;
    }
    // Anlauflogik
    /*if(abs(processvalue) < 200)
    {
        int16_t boost = 200 - (abs(processvalue));
        return (setpoint > 0) ? boost : -boost;
    }
    if(setpoint > 0 && setpoint < 400)
        setpoint = 400;
    else if(setpoint < 0 && setpoint > -400)
        setpoint = -400;
*/
    float error = (float)(setpoint - processvalue);
    float newintegral = integral + error;

    float controlvariable = KP * error + KI * DT * integral;

    // Anti-Windup - Begrenzen
    if(controlvariable > CONTROLLIMIT)
    {
    	controlvariable = CONTROLLIMIT;
    	if (error < 0) {
    		integral = newintegral;
    	}
    } else if(controlvariable < -CONTROLLIMIT)
    {
    	controlvariable = -CONTROLLIMIT;
    	if (error > 0) {
    		integral = newintegral;
    	}
    } else {
		integral = newintegral;
    }
    /*
    if(abs(processvalue) < 60)  // Motor steht quasi
    {
    	if(controlvariable > 0 && controlvariable < 100)
    		controlvariable = 100;
    	else if(controlvariable < 0 && controlvariable > -100)
    		controlvariable = -100;
    }*/
    return (int16_t)controlvariable;
}


void updateramp(void)
{
    if(controlvariable < controlvariableinput)
    {
        controlvariable += RAMPSTEP;
        if(controlvariable > controlvariableinput)
            controlvariable = controlvariableinput;
    }
    else if(controlvariable > controlvariableinput)
    {
    	controlvariable -= RAMPSTEP;
        if(controlvariable < controlvariableinput)
        	controlvariable = controlvariableinput;
    }
}


void error (int status) {
  int sts = status;
  if (status < 0) {
    sts = -status;
  }

  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_9, GPIO_PIN_SET);

  for (int i = 0; i < sts; i++) {

	HAL_Delay(300);
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, GPIO_PIN_RESET);
	HAL_Delay(300);
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, GPIO_PIN_SET);

  }
  HAL_Delay(300);
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_9, GPIO_PIN_RESET);
}


uint8_t iam() {

  return hwbits;

}

void delay_ms(uint16_t ms) {

    __HAL_TIM_SET_COUNTER(&htim4, 0);  // reset counter
    HAL_TIM_Base_Start(&htim4); // Start the timer
    while (__HAL_TIM_GET_COUNTER(&htim4) < ms);
    HAL_TIM_Base_Stop(&htim4); // Start the timer
}

void delay_us(uint32_t us) {

    __HAL_TIM_SET_COUNTER(&htim5, 0);  // reset counter
    HAL_TIM_Base_Start(&htim5); // Start the timer
    while (__HAL_TIM_GET_COUNTER(&htim5) < us);
    HAL_TIM_Base_Stop(&htim5); // Start the timer
}

uint8_t checksum(const uint8_t *data, uint8_t len) {
	uint16_t checksum = 0;
    for (uint8_t i = 0; i < len; i++) {
        checksum += data[i];
        if (checksum > 0xFF) {
            checksum = (checksum & 0xFF) + 1; // Carry addieren
        }
    }

    return (uint8_t)(~checksum);
}

void fillbody(uint8_t addr, uint8_t *data, uint8_t len) {
  
  if(addr == st0mot) {
    GPIO_PinState high = HAL_GPIO_ReadPin (GPIOC, GPIO_PIN_0); // high, see arduino above
    GPIO_PinState middle = HAL_GPIO_ReadPin (GPIOC, GPIO_PIN_1); // middle, see arduino above
    GPIO_PinState low = HAL_GPIO_ReadPin (GPIOC, GPIO_PIN_2); // low, see arduino above
    data[0] = (high == GPIO_PIN_RESET) ? 0x00 : 0x01;
    data[1] = (middle == GPIO_PIN_RESET) ? 0x00 : 0x01;
    data[2] = (low == GPIO_PIN_RESET) ? 0x00 : 0x01;
  } else if(addr == st1mot) {
    HAL_ADC_Start(&hadc2);
    HAL_ADC_PollForConversion(&hadc2, 10);
    uint32_t val = HAL_ADC_GetValue(&hadc2);
    data[0] = 0xFF & val;
    data[1] = (0xFF00 & val) >> 8;
  } else if(addr == st2mot) {
    data[0] = 0xFF & rpm;
    data[1] = (0xFF00 & rpm) >> 8;
  } else if (addr == st3mot) {
    data[0] = (uint8_t)(bodyTimeoutCount & 0xFF);
    data[1] = (uint8_t)((bodyTimeoutCount >> 8) & 0xFF);
    data[2] = (uint8_t)(checksumErrorCount & 0xFF);
    data[3] = (uint8_t)((checksumErrorCount >> 8) & 0xFF);
  }
}

uint8_t addparity(uint8_t addr) {
  uint8_t temp = addr & 0x3f;
  uint8_t p0 = BIT(temp,0) + BIT(temp,1) + BIT(temp,2) + BIT(temp,4);
  p0 &= 0x01;
  uint8_t p1 = BIT(temp,1) + BIT(temp,3) + BIT(temp,4) + BIT(temp,5);
  p1 = (~p1) & 0x01;

  return addr | (p0 << 6) | (p1 << 7);
}

int8_t getindex(uint8_t addr) {
	int8_t linindex = 0;
	for (unsigned int i = 0; i < sizeof(pids); i++) {
	  if (pids[i] == addr) {
		linindex = i;
		return linindex;
	  }
	}
	return LIN_PID_ERR;

}
/* USER CODE END 4 */

 /* MPU Configuration */

void MPU_Config(void)
{
  MPU_Region_InitTypeDef MPU_InitStruct = {0};

  /* Disables the MPU */
  HAL_MPU_Disable();

  /** Initializes and configures the Region and the memory to be protected
  */
  MPU_InitStruct.Enable = MPU_REGION_ENABLE;
  MPU_InitStruct.Number = MPU_REGION_NUMBER0;
  MPU_InitStruct.BaseAddress = 0x0;
  MPU_InitStruct.Size = MPU_REGION_SIZE_4GB;
  MPU_InitStruct.SubRegionDisable = 0x87;
  MPU_InitStruct.TypeExtField = MPU_TEX_LEVEL0;
  MPU_InitStruct.AccessPermission = MPU_REGION_NO_ACCESS;
  MPU_InitStruct.DisableExec = MPU_INSTRUCTION_ACCESS_DISABLE;
  MPU_InitStruct.IsShareable = MPU_ACCESS_SHAREABLE;
  MPU_InitStruct.IsCacheable = MPU_ACCESS_NOT_CACHEABLE;
  MPU_InitStruct.IsBufferable = MPU_ACCESS_NOT_BUFFERABLE;

  HAL_MPU_ConfigRegion(&MPU_InitStruct);
  /* Enables the MPU */
  HAL_MPU_Enable(MPU_PRIVILEGED_DEFAULT);

}



/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}






// Funktionen entweder vor der ersten Nutzung schreiben oder oben einmal deklarieren also mit void allOff();
void allOff(){            // alles aus, um Kurzschluss zu vermeiden

  HAL_GPIO_WritePin(GPIOE, GPIO_PIN_8, GPIO_PIN_RESET); // AL
  HAL_GPIO_WritePin(GPIOE, GPIO_PIN_9, GPIO_PIN_RESET); // AH
  HAL_GPIO_WritePin(GPIOE, GPIO_PIN_10, GPIO_PIN_RESET); // BL
  HAL_GPIO_WritePin(GPIOE, GPIO_PIN_11, GPIO_PIN_RESET); // BH
  HAL_GPIO_WritePin(GPIOE, GPIO_PIN_12, GPIO_PIN_RESET); // CL
  HAL_GPIO_WritePin(GPIOE, GPIO_PIN_13, GPIO_PIN_RESET); // CH

}

void driveMOSFET(int pin, GPIO_PinState st)
{
	if (pin == AL) {
		HAL_GPIO_WritePin(GPIOE, GPIO_PIN_8, st); // AL
	}
	if (pin == AH) {
		HAL_GPIO_WritePin(GPIOE, GPIO_PIN_9, st); // AH
	}
	if (pin == BL) {
		HAL_GPIO_WritePin(GPIOE, GPIO_PIN_10, st); // BL
	}
	if (pin == BH) {
		HAL_GPIO_WritePin(GPIOE, GPIO_PIN_11, st); // BH
	}
	if (pin == CL) {
		HAL_GPIO_WritePin(GPIOE, GPIO_PIN_12, st); // CL
	}
	if (pin == CH) {
		HAL_GPIO_WritePin(GPIOE, GPIO_PIN_13, st); // CH
	}
}

void driveState(uint16_t speed, int st)
{

	allOff();
	if (speed == 0) {
		return;
	}
	uint32_t chargetime = 10;//50
	uint32_t rate = GLOBALRATE; //1275;//2550
	uint32_t speedrate = (uint32_t)speed;//10
	if (rate <= speedrate) {
		delay_us(GLOBALRATE);
		return;
	}

	if (st == 0) {
		driveMOSFET(AL, GPIO_PIN_SET);
		driveMOSFET(BL, GPIO_PIN_SET);
		delay_us(chargetime);
		driveMOSFET(BL, GPIO_PIN_RESET);
		driveMOSFET(BH, GPIO_PIN_SET);
	}
	if (st == 1) {
		driveMOSFET(AL, GPIO_PIN_SET);
		driveMOSFET(CL, GPIO_PIN_SET);
		delay_us(chargetime);
		driveMOSFET(CL, GPIO_PIN_RESET);
		driveMOSFET(CH, GPIO_PIN_SET);
	}
	if (st == 2) {
		driveMOSFET(BL, GPIO_PIN_SET);
		driveMOSFET(CL, GPIO_PIN_SET);
		delay_us(chargetime);
		driveMOSFET(CL, GPIO_PIN_RESET);
		driveMOSFET(CH, GPIO_PIN_SET);
	}
	if (st == 3) {
		driveMOSFET(BL, GPIO_PIN_SET);
		driveMOSFET(AL, GPIO_PIN_SET);
		delay_us(chargetime);
		driveMOSFET(AL, GPIO_PIN_RESET);
		driveMOSFET(AH, GPIO_PIN_SET);
	}
	if (st == 4) {
		driveMOSFET(CL, GPIO_PIN_SET);
		driveMOSFET(AL, GPIO_PIN_SET);
		delay_us(chargetime);
		driveMOSFET(AL, GPIO_PIN_RESET);
		driveMOSFET(AH, GPIO_PIN_SET);
	}
	if (st == 5) {
		driveMOSFET(CL, GPIO_PIN_SET);
		driveMOSFET(BL, GPIO_PIN_SET);
		delay_us(chargetime);
		driveMOSFET(BL, GPIO_PIN_RESET);
		driveMOSFET(BH, GPIO_PIN_SET);
	}
	delay_us(speedrate);
	allOff();
	delay_us(GLOBALRATE-speedrate);
}




uint8_t getState()
{
	GPIO_PinState high = HAL_GPIO_ReadPin (GPIOC, GPIO_PIN_0);
	GPIO_PinState middle = HAL_GPIO_ReadPin (GPIOC, GPIO_PIN_1);
	GPIO_PinState low = HAL_GPIO_ReadPin (GPIOC, GPIO_PIN_2);
	uint8_t first = (high == GPIO_PIN_RESET) ? 0x00 : 0x01;
	uint8_t second  = (middle == GPIO_PIN_RESET) ? 0x00 : 0x01;
	uint8_t third = (low == GPIO_PIN_RESET) ? 0x00 : 0x01;

	if (first == 0x01 && second == 0x0 && third == 0x0) { // state 4
		return 4;
	}
	if (first == 0x01 && second == 0x0 && third == 0x01) { // state 5
		return 5;
	}
	if (first == 0x0 && second == 0x0 && third == 0x01) { // state 0
		return 0;
	}
	if (first == 0x0 && second == 0x1 && third == 0x1) { // state 1
		return 1;
	}
	if (first == 0x0 && second == 0x01 && third == 0x0) { // state 2
		return 2;
	}
	if (first == 0x01 && second == 0x1 && third == 0x0) { //state 3
		return 3;
	}
	return 6;
}

uint8_t driveStep(int16_t speed)
{

	GPIO_PinState high = HAL_GPIO_ReadPin (GPIOC, GPIO_PIN_0); //gelb
	GPIO_PinState middle = HAL_GPIO_ReadPin (GPIOC, GPIO_PIN_1); //rot
	GPIO_PinState low = HAL_GPIO_ReadPin (GPIOC, GPIO_PIN_2); //blau
	uint8_t first = (high == GPIO_PIN_RESET) ? 0x00 : 0x01; //gelb
	uint8_t second  = (middle == GPIO_PIN_RESET) ? 0x00 : 0x01; //rot
	uint8_t third = (low == GPIO_PIN_RESET) ? 0x00 : 0x01;//blau

	if (speed >= 0) { // CW -> stated ascending
		if (first == 0x01 && second == 0x0 && third == 0x0) { // state 4 100
			driveState(abs(speed), 5); // 101
			return 4;
		}
		if (first == 0x01 && second == 0x0 && third == 0x01) { // state 5 101
			driveState(abs(speed), 0); // 001
			return 5;
		}
		if (first == 0x0 && second == 0x0 && third == 0x01) { // state 0 001
			driveState(abs(speed), 1); // 011
			return 0;
		}
		if (first == 0x0 && second == 0x1 && third == 0x1) { // state 1 011
			driveState(abs(speed), 2); // 020
			return 1;
		}
		if (first == 0x0 && second == 0x01 && third == 0x0) { // state 2 010
			driveState(abs(speed), 3); // 110
			return 2;
		}
		if (first == 0x01 && second == 0x1 && third == 0x0) { //state 3 110
			driveState(abs(speed), 4); // 110
			return 3;
		}
	}
	if (speed < 0) { // CCW -> states descending
		if (first == 0x0 && second == 0x1 && third == 0x0) { // state 2 010
			driveState(abs(speed), 4);
			return 2;
		}
		if (first == 0x0 && second == 0x01 && third == 0x01) { // state 1 011
			driveState(abs(speed), 3);
			return 1;
		}
		if (first == 0x0 && second == 0x0 && third == 0x01) { // state 0 001
			driveState(abs(speed), 2);
			return 0;
		}
		if (first == 0x01 && second == 0x0 && third == 0x1) { // state 5 101
			driveState(abs(speed), 1);
			return 5;
		}
		if (first == 0x01 && second == 0x0 && third == 0x0) { // state 4 100
			driveState(abs(speed), 0);
			return 4;
		}
		if (first == 0x01 && second == 0x1 && third == 0x0) { // state 3 110
			driveState(abs(speed), 5);
			return 3;
		}
	}
	return 6;
}


#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
