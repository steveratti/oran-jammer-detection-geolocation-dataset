/* -*- Mode: C++; c-file-style: "gnu"; indent-tabs-mode:nil; -*- */
/* *
 * Copyright (c) 2024 Orange Innovation Poland
 * Copyright (c) 2024 Orange Innovation Egypt
 * This program is free software;
 * you can redistribute it and/or modify
 * it under the terms of the GNU General Public License version 2 as
 * published by the Free Software Foundation;
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY;
 * without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 * See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program;
 * if not, write to the Free Software
 * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA
 *
 * Authors: Andrea Lacava <thecave003@gmail.com>
 * Michele Polese <michele.polese@gmail.com>
 * Argha Sen <arghasen10@gmail.com>
 * Kamil Kociszewski <kamil.kociszewski@orange.com>
 * Mostafa Ashraf <mostafa.ashraf.ext@orange.com>
 */
#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/applications-module.h"
#include "ns3/point-to-point-helper.h"
#include <ns3/lte-ue-net-device.h>
#include "ns3/mmwave-helper.h"
#include "ns3/epc-helper.h"
#include "ns3/mmwave-point-to-point-epc-helper.h"
#include "../src/mmwave/model/node-container-manager.h"
#include "ns3/lte-helper.h"
// JAMMER FIX
#include "ns3/channel-condition-model.h"
#include "ns3/isotropic-antenna-model.h"
#include "ns3/mmwave-enb-phy.h"
#include "ns3/three-gpp-propagation-loss-model.h"
#include <sys/time.h>
#include <ctime>
#include <sys/types.h>
#include <iostream>
#include <stdlib.h>
#include <list>
#include <random>
#include <chrono>
#include <cmath>
#include <fstream>

using namespace ns3;
using namespace mmwave;

std::map<uint64_t, uint16_t> imsi_cellid;
std::map<uint16_t, std::set<uint64_t>> imsi_list;
std::map<uint16_t, Ptr < Node>>
cellid_node;
std::map<uint32_t, uint16_t> ue_cellid_usinghandover;
std::map<uint64_t, uint32_t> ueimsi_nodeid;
int ue_assoc_list[50] = {0}; // Increased for 15 UEs
double maxXAxis;
double maxYAxis;

int num_of_mmdev = 0;

/**
 * Scenario Zero
 *
 */

NS_LOG_COMPONENT_DEFINE ("ScenarioZero");
void
PrintGnuplottableUeListToFile(std::string filename) {
    std::ofstream outFile;
    outFile.open(filename.c_str(), std::ios_base::out | std::ios_base::trunc);
    if (!outFile.is_open()) {
        NS_LOG_ERROR("Can't open file " << filename);
        return;
    }
    for (NodeList::Iterator it = NodeList::Begin(); it != NodeList::End(); ++it) {
        Ptr <Node> node = *it;
        int nDevs = node->GetNDevices();
        for (int j = 0; j < nDevs; j++) {
            Ptr <LteUeNetDevice> uedev = node->GetDevice(j)->GetObject<LteUeNetDevice>();
            Ptr <MmWaveUeNetDevice> mmuedev = node->GetDevice(j)->GetObject<MmWaveUeNetDevice>();
            Ptr <McUeNetDevice> mcuedev = node->GetDevice(j)->GetObject<McUeNetDevice>();
            if (uedev) {
                Vector pos = node->GetObject<MobilityModel>()->GetPosition();
                outFile << "set label \"" << uedev->GetImsi() << "\" at " << pos.x << "," << pos.y
                        << " left font \"Helvetica,8\" textcolor rgb \"black\" front point pt 1 ps "
                           "0.3 lc rgb \"black\" offset 0,0"
                        << std::endl;
            } else if (mmuedev) {
                Vector pos = node->GetObject<MobilityModel>()->GetPosition();
                outFile << "set label \"" << mmuedev->GetImsi() << "\" at " << pos.x << "," << pos.y
                        << " left font \"Helvetica,8\" textcolor rgb \"black\" front point pt 1 ps "
                           "0.3 lc rgb \"black\" offset 0,0"
                        << std::endl;
            } else if (mcuedev) {
                Vector pos = node->GetObject<MobilityModel>()->GetPosition();
                outFile << "set label \"" << mcuedev->GetImsi() << "\" at " << pos.x << "," << pos.y
                        << " left font \"Helvetica,8\" textcolor rgb \"black\" front point pt 1 ps "
                           "0.3 lc rgb \"black\" offset 0,0"
                        << std::endl;
            }
        }
    }
}



void
PrintGnuplottableEnbListToFile(uint64_t m_startTime) {

  uint64_t timestamp = m_startTime + (uint64_t) Simulator::Now().GetMilliSeconds();
  std::string filename1 = "enbs.txt";
  std::string filename2 = "gnbs.txt";

  for (NodeList::Iterator it = NodeList::Begin(); it != NodeList::End(); ++it) {
      Ptr <Node> node = *it;
      int nDevs = node->GetNDevices();
      for (int j = 0; j < nDevs; j++) {
          Ptr <LteEnbNetDevice> enbdev = node->GetDevice(j)->GetObject<LteEnbNetDevice>();
          Ptr <MmWaveEnbNetDevice> mmdev = node->GetDevice(j)->GetObject<MmWaveEnbNetDevice>();
          if (enbdev) {
              Vector pos = node->GetObject<MobilityModel>()->GetPosition();
              std::ofstream outFile1;
              outFile1.open(filename1.c_str(), std::ios_base::out | std::ios_base::app);
              if (!outFile1.is_open()) {
                  NS_LOG_ERROR("Can't open file " << filename1);
                  return;
                }
              outFile1 << timestamp << "," << enbdev->GetCellId() << "," << pos.x << "," << pos.y << ","
                       << m_startTime << "," << "0" << "," << "30" << std::endl;
              outFile1.close();
            } else if (mmdev) {
                Vector pos = node->GetObject<MobilityModel>()->GetPosition();
                std::ofstream outFile2;
                outFile2.open(filename2.c_str(), std::ios_base::out | std::ios_base::app);
                if (!outFile2.is_open()) {
                    NS_LOG_ERROR("Can't open file " << filename2);
                    return;
                }
                auto ueMap = mmdev->GetUeMap();
                for (const auto &ue: ueMap) {
                    uint64_t imsi_assoc = ue.second->GetImsi();
                    ue_assoc_list[imsi_assoc - 1] = mmdev->GetCellId();
                }
                uint16_t cell_id = mmdev->GetCellId();
                outFile2 << timestamp << "," << cell_id << "," << pos.x << "," << pos.y << ","
                         << m_startTime << "," << "0" << ","
                         << "0" << "," << "0"
                         << "," << "0" << std::endl;
                outFile2.close ();
            }
        }
    }
}

void
ClearFile(std::string Filename, uint64_t m_startTime) {
    std::string filename = Filename;
    std::ofstream outFile;
    outFile.open(filename.c_str(), std::ios_base::out | std::ios_base::trunc);
    if (!outFile.is_open()) {
        NS_LOG_ERROR("Can't open file " << filename);
        return;
    }
    outFile.close();

    uint64_t timestamp = m_startTime + (uint64_t) Simulator::Now().GetMilliSeconds();
    std::ofstream outFile1;
    outFile1.open(filename.c_str(), std::ios_base::out | std::ios_base::app);

    if (Filename == "ue_position.txt") {
        outFile1 << "timestamp,id,x,y,type,cell,simid" << std::endl;
    }
    else
    {
        outFile1 << "timestamp,id,x,y,simid,ESstate,currEC,maxEC,totalcurrEC" << std::endl;
        outFile1 << timestamp << "," << "0" << "," << maxXAxis << "," << maxYAxis << std::endl;
    }
    outFile1.close();
}

void
PrintPosition(Ptr<Node> node, int iterator, std::string Filename, uint64_t m_startTime) {

    uint64_t timestamp = m_startTime + (uint64_t) Simulator::Now().GetMilliSeconds();

    int imsi;
    Ptr <Node> node1 = node; // JAMMER FIX: was NodeList::GetNode(iterator) -> IMSI of the next UE
    int nDevs = node->GetNDevices();
    std::string filename = Filename;
    std::ofstream outFile;
    for (int j = 0; j < nDevs; j++) {
        Ptr <McUeNetDevice> mcuedev = node1->GetDevice(j)->GetObject<McUeNetDevice>();
        if (mcuedev) {
            imsi = int(mcuedev->GetImsi());
            int serving_cell;
            // Removed the problematic conditional check
            // if (imsi > 35 || ue_assoc_list[imsi - 1] == 0) { 
            //    return;
            // }
            // else
            // {
            serving_cell = ue_assoc_list[imsi - 1];
            // }

            Ptr<MobilityModel> model = node->GetObject<MobilityModel> ();
            Vector position = model->GetPosition ();
            NS_LOG_UNCOND ("Position of UE with IMSI " << imsi << " is " << model->GetPosition ()
                            << " at time "
                            << Simulator::Now ().GetSeconds ()
                            << ", UE connected to Cell: "
                            << serving_cell);
            outFile.open(filename.c_str(), std::ios_base::out | std::ios_base::app);
            if (!outFile.is_open()) {
                NS_LOG_ERROR("Can't open file " << filename);
                return;
            }

            outFile << timestamp << "," << imsi << "," << position.x << "," << position.y << ",mc,"
                    << serving_cell << "," << m_startTime << std::endl;
            outFile.close ();
        }
    }
}



static ns3::GlobalValue g_bufferSize("bufferSize", "RLC tx buffer size (MB)",
                                    ns3::UintegerValue(10),
                                    ns3::MakeUintegerChecker<uint32_t>());
static ns3::GlobalValue g_enableTraces("enableTraces", "If true, generate ns-3 traces",
                                        ns3::BooleanValue(true), ns3::MakeBooleanChecker());
static ns3::GlobalValue g_e2lteEnabled("e2lteEnabled", "If true, send LTE E2 reports",
                                        ns3::BooleanValue(true), ns3::MakeBooleanChecker());
static ns3::GlobalValue g_e2nrEnabled("e2nrEnabled", "If true, send NR E2 reports",
                                     ns3::BooleanValue(true), ns3::MakeBooleanChecker());
static ns3::GlobalValue g_e2du("e2du", "If true, send DU reports", ns3::BooleanValue(true),
                               ns3::MakeBooleanChecker());
static ns3::GlobalValue g_e2cuUp("e2cuUp", "If true, send CU-UP reports", ns3::BooleanValue(true),
                                 ns3::MakeBooleanChecker());
static ns3::GlobalValue g_e2cuCp("e2cuCp", "If true, send CU-CP reports", ns3::BooleanValue(true),
                                 ns3::MakeBooleanChecker());
static ns3::GlobalValue g_reducedPmValues("reducedPmValues", "If true, use a subset of the the pm containers",
                                         ns3::BooleanValue(false), ns3::MakeBooleanChecker());

static ns3::GlobalValue
        g_hoSinrDifference("hoSinrDifference",
                           "The value for which an handover between MmWave eNB is triggered",
                           ns3::DoubleValue(0.0),
                           ns3::MakeDoubleChecker<double>());

static ns3::GlobalValue g_indicationPeriodicity(
    "indicationPeriodicity",
    "E2 Indication Periodicity reports (value in seconds)",
    ns3::DoubleValue(0.05),
    ns3::MakeDoubleChecker<double>(0.01, 2.0));
static ns3::GlobalValue g_simTime("simTime",
                                  "Simulation time in seconds",
                                  ns3::DoubleValue(60.0),
                                  ns3::MakeDoubleChecker<double>(0.1, 100000.0));
static ns3::GlobalValue g_outageThreshold("outageThreshold",
                                          "SNR threshold for outage events [dB]",
                                          ns3::DoubleValue(-15.0),
                                          ns3::MakeDoubleChecker<double>());
static ns3::GlobalValue g_numberOfRaPreambles(
    "numberOfRaPreambles",
    "how many random access preambles are available for the contention based RACH process",
    ns3::UintegerValue(40),
    ns3::MakeUintegerChecker<uint8_t>());
static ns3::GlobalValue
        g_handoverMode("handoverMode",
                       "HO euristic to be used,"
                       "can be only \"NoAuto\", \"FixedTtt\", \"DynamicTtt\", \"Threshold\"",
                       ns3::StringValue("Threshold"), ns3::MakeStringChecker());

static ns3::GlobalValue g_e2TermIp("e2TermIp", "The IP address of the RIC E2 termination",
                                   ns3::StringValue("127.0.0.1"), ns3::MakeStringChecker());
static ns3::GlobalValue
        g_enableE2FileLogging("enableE2FileLogging",
                              "If true, generate offline file logging instead of connecting to RIC",
                              ns3::BooleanValue(false), ns3::MakeBooleanChecker());
static ns3::GlobalValue g_e2_func_id("KPM_E2functionID", "Function ID to subscribe",
                                     ns3::DoubleValue(2),
                                     ns3::MakeDoubleChecker<double>());
static ns3::GlobalValue g_rc_e2_func_id("RC_E2functionID", "Function ID to subscribe",
                                        ns3::DoubleValue(3),
                                        ns3::MakeDoubleChecker<double>());
static ns3::GlobalValue g_controlFileName("controlFileName",
                                          "The path to the control file (can be absolute)",
                                          ns3::StringValue(""),
                                          ns3::MakeStringChecker());
static ns3::GlobalValue mmWave_nodes ("N_MmWaveEnbNodes", "Number of mmWaveNodes",
                                      ns3::UintegerValue (4),
                                      ns3::MakeUintegerChecker<uint8_t> ());
static ns3::GlobalValue ue_s ("N_Ues", "Number of User Equipments",
                              ns3::UintegerValue (10),
                              ns3::MakeUintegerChecker<uint32_t> ());
static ns3::GlobalValue center_freq ("CenterFrequency", "Center Frequency Value",
                                      ns3::DoubleValue (3.5e9),
                                      ns3::MakeDoubleChecker<double> ());
static ns3::GlobalValue bandwidth_value ("Bandwidth", "Bandwidth Value",
                                         ns3::DoubleValue (20e6),
                                         ns3::MakeDoubleChecker<double> ());
static ns3::GlobalValue interside_distance_value_ue ("IntersideDistanceUEs", "Interside Distance Value",
                                                     ns3::DoubleValue (400),
                                                     ns3::MakeDoubleChecker<double> ());
static ns3::GlobalValue interside_distance_value_cell ("IntersideDistanceCells", "Interside Distance Value",
                                                       ns3::DoubleValue (200),
                                                       ns3::MakeDoubleChecker<double> ());

int
main(int argc, char *argv[]) {
    Config::SetDefault("ns3::MmWaveUePhy::NoiseFigure", DoubleValue(9.0));
    Config::SetDefault("ns3::ThreeGppChannelModel::Blockage", BooleanValue(true));
//     LogComponentEnable ("LteEnbRrc", LOG_LEVEL_DEBUG);
//     LogComponentEnable ("MmWaveEnbNetDevice", LOG_LEVEL_DEBUG);

    maxXAxis = 1000;
    maxYAxis = 1000;
    // JAMMER FIX: jammer parameters (command line)
    bool jammerOn = true;          // false = jammer-free control run (same seed, same topology)
    double jammerX = 710.0;        // near gNB 3 (700, 500)
    double jammerY = 510.0;
    double jammerZ = 1.5;
    double jammerPowerDbm = 60.0;  // jammer EIRP [dBm], sweep e.g. 40/50/60/70

    CommandLine cmd;
    cmd.AddValue("jammerOn", "Enable the jammer (false = jammer-free control run)", jammerOn);
    cmd.AddValue("jammerX", "Jammer x position [m]", jammerX);
    cmd.AddValue("jammerY", "Jammer y position [m]", jammerY);
    cmd.AddValue("jammerZ", "Jammer height [m]", jammerZ);
    cmd.AddValue("jammerPowerDbm", "Jammer EIRP [dBm]", jammerPowerDbm);
    cmd.Parse(argc, argv); // use --RngRun=<n> for independent Monte Carlo runs

    bool harqEnabled = true;

    UintegerValue uintegerValue;
    BooleanValue booleanValue;
    StringValue stringValue;
    DoubleValue doubleValue;

    GlobalValue::GetValueByName("hoSinrDifference", doubleValue);
    double hoSinrDifference = doubleValue.Get();
    GlobalValue::GetValueByName("bufferSize", uintegerValue);
    uint32_t bufferSize = uintegerValue.Get();
    GlobalValue::GetValueByName("enableTraces", booleanValue);
    bool enableTraces = booleanValue.Get();
    GlobalValue::GetValueByName("outageThreshold", doubleValue);
    double outageThreshold = doubleValue.Get();
    GlobalValue::GetValueByName("handoverMode", stringValue);
    std::string handoverMode = stringValue.Get();

    NS_LOG_UNCOND("--- VERIFYING HANDOVER CONFIGURATION ---");
    NS_LOG_UNCOND("Mode = " << handoverMode << " | SINR Difference = " << hoSinrDifference << " | Outage Threshold = " << outageThreshold);

    GlobalValue::GetValueByName("e2TermIp", stringValue);
    std::string e2TermIp = stringValue.Get();
    GlobalValue::GetValueByName("enableE2FileLogging", booleanValue);
    bool enableE2FileLogging = booleanValue.Get();
    GlobalValue::GetValueByName("KPM_E2functionID", doubleValue);
    double g_e2_func_id = doubleValue.Get();
    GlobalValue::GetValueByName("RC_E2functionID", doubleValue);
    double g_rc_e2_func_id = doubleValue.Get();


    GlobalValue::GetValueByName("numberOfRaPreambles", uintegerValue);
    uint8_t numberOfRaPreambles = uintegerValue.Get();
    NS_LOG_UNCOND("bufferSize " << bufferSize << " OutageThreshold " << outageThreshold
                                 << " HandoverMode " << handoverMode << " e2TermIp " << e2TermIp
                                 << " enableE2FileLogging " << enableE2FileLogging
                                 << " E2 Function ID " << g_e2_func_id);
    GlobalValue::GetValueByName("e2lteEnabled", booleanValue);
    bool e2lteEnabled = booleanValue.Get();
    GlobalValue::GetValueByName("e2nrEnabled", booleanValue);
    bool e2nrEnabled = booleanValue.Get();
    GlobalValue::GetValueByName("e2du", booleanValue);
    bool e2du = booleanValue.Get();
    GlobalValue::GetValueByName("e2cuUp", booleanValue);
    bool e2cuUp = booleanValue.Get();
    GlobalValue::GetValueByName("e2cuCp", booleanValue);
    bool e2cuCp = booleanValue.Get();

    GlobalValue::GetValueByName("reducedPmValues", booleanValue);
    bool reducedPmValues = booleanValue.Get();

    GlobalValue::GetValueByName("indicationPeriodicity", doubleValue);
    double indicationPeriodicity = doubleValue.Get();
    GlobalValue::GetValueByName("controlFileName", stringValue);
    std::string controlFilename = stringValue.Get();
    NS_LOG_UNCOND("e2lteEnabled " << e2lteEnabled << " e2nrEnabled " << e2nrEnabled << " e2du "
                                  << e2du << " e2cuCp " << e2cuCp << " e2cuUp " << e2cuUp
                                  << " controlFilename " << controlFilename
                                  << " indicationPeriodicity " << indicationPeriodicity);
    Config::SetDefault("ns3::LteEnbNetDevice::ControlFileName", StringValue(controlFilename));
    Config::SetDefault("ns3::LteEnbNetDevice::E2Periodicity", DoubleValue(indicationPeriodicity));
    Config::SetDefault("ns3::MmWaveEnbNetDevice::E2Periodicity",
                       DoubleValue(indicationPeriodicity));
    Config::SetDefault("ns3::MmWaveHelper::E2ModeLte", BooleanValue(e2lteEnabled));
    Config::SetDefault("ns3::MmWaveHelper::E2ModeNr", BooleanValue(e2nrEnabled));

    Config::SetDefault("ns3::MmWaveEnbNetDevice::EnableDuReport", BooleanValue(e2du));
    Config::SetDefault("ns3::MmWaveEnbNetDevice::EnableCuUpReport", BooleanValue(e2cuUp));
    Config::SetDefault("ns3::LteEnbNetDevice::EnableCuUpReport", BooleanValue(e2cuUp));

    Config::SetDefault("ns3::MmWaveEnbNetDevice::EnableCuCpReport", BooleanValue(e2cuCp));
    Config::SetDefault("ns3::LteEnbNetDevice::EnableCuCpReport", BooleanValue(e2cuCp));

    Config::SetDefault("ns3::MmWaveEnbNetDevice::ReducedPmValues", BooleanValue(reducedPmValues));
    Config::SetDefault("ns3::LteEnbNetDevice::ReducedPmValues", BooleanValue(reducedPmValues));
    Config::SetDefault("ns3::LteEnbNetDevice::EnableE2FileLogging",
                       BooleanValue(enableE2FileLogging));
    Config::SetDefault("ns3::MmWaveEnbNetDevice::EnableE2FileLogging",
                       BooleanValue(enableE2FileLogging));
    Config::SetDefault("ns3::LteEnbNetDevice::KPM_E2functionID",
                       DoubleValue(g_e2_func_id));
    Config::SetDefault("ns3::MmWaveEnbNetDevice::KPM_E2functionID",
                       DoubleValue(g_e2_func_id));
    Config::SetDefault("ns3::LteEnbNetDevice::RC_E2functionID",
                       DoubleValue(g_rc_e2_func_id));
    Config::SetDefault("ns3::MmWaveEnbMac::NumberOfRaPreambles",
                       UintegerValue(numberOfRaPreambles));
    Config::SetDefault("ns3::MmWaveHelper::HarqEnabled", BooleanValue(harqEnabled));
    Config::SetDefault("ns3::MmWaveHelper::UseIdealRrc", BooleanValue(true));
    Config::SetDefault("ns3::MmWaveHelper::E2TermIp", StringValue(e2TermIp));

    Config::SetDefault("ns3::MmWaveFlexTtiMacScheduler::HarqEnabled", BooleanValue(harqEnabled));
    Config::SetDefault("ns3::MmWavePhyMacCommon::NumHarqProcess", UintegerValue(100));
    Config::SetDefault("ns3::PhasedArrayModel::AntennaElement",
                       PointerValue(CreateObject<IsotropicAntennaModel>())); // JAMMER FIX (ns-3.42)
    Config::SetDefault("ns3::ThreeGppChannelModel::UpdatePeriod", TimeValue(MilliSeconds(100.0)));
    Config::SetDefault("ns3::ThreeGppChannelConditionModel::UpdatePeriod",
                       TimeValue(MilliSeconds(100)));
    Config::SetDefault("ns3::LteRlcAm::ReportBufferStatusTimer", TimeValue(MilliSeconds(10.0)));
    Config::SetDefault("ns3::LteRlcUmLowLat::ReportBufferStatusTimer",
                       TimeValue(MilliSeconds(10.0)));
    Config::SetDefault("ns3::LteRlcUm::MaxTxBufferSize", UintegerValue(bufferSize * 1024 * 1024));
    Config::SetDefault("ns3::LteRlcUmLowLat::MaxTxBufferSize",
                       UintegerValue(bufferSize * 1024 * 1024));
    Config::SetDefault("ns3::LteRlcAm::MaxTxBufferSize", UintegerValue(bufferSize * 1024 * 1024));

    Config::SetDefault("ns3::LteEnbRrc::OutageThreshold", DoubleValue(outageThreshold));
    Config::SetDefault("ns3::LteEnbRrc::SecondaryCellHandoverMode", StringValue("Threshold"));
    Config::SetDefault("ns3::LteEnbRrc::HoSinrDifference", DoubleValue(hoSinrDifference));


    Config::SetDefault("ns3::ThreeGppPropagationLossModel::Frequency",DoubleValue(3.5e9));
    Config::SetDefault("ns3::ThreeGppPropagationLossModel::ShadowingEnabled",BooleanValue(true));
    GlobalValue::GetValueByName ("Bandwidth", doubleValue);
    double bandwidth = doubleValue.Get();
    GlobalValue::GetValueByName ("CenterFrequency", doubleValue);
    double centerFrequency = doubleValue.Get();
    GlobalValue::GetValueByName ("IntersideDistanceUEs", doubleValue);
    double isd_ue = doubleValue.Get(); 
    GlobalValue::GetValueByName ("IntersideDistanceCells", doubleValue);
    double isd_cell = doubleValue.Get();

    int numAntennasMcUe = 1;
    int numAntennasMmWave = 1;

    NS_LOG_INFO("Bandwidth " << bandwidth << " centerFrequency " << double(centerFrequency)
                                 << " isd_ue " << isd_ue << " numAntennasMcUe " << numAntennasMcUe
                                 << " numAntennasMmWave " << numAntennasMmWave);
    Config::SetDefault("ns3::McUeNetDevice::AntennaNum", UintegerValue(numAntennasMcUe));
    Config::SetDefault("ns3::MmWaveNetDevice::AntennaNum", UintegerValue(numAntennasMmWave));
    Config::SetDefault("ns3::MmWavePhyMacCommon::Bandwidth", DoubleValue(bandwidth));
    Config::SetDefault("ns3::MmWavePhyMacCommon::CenterFreq", DoubleValue(centerFrequency));
    Ptr <MmWaveHelper> mmwaveHelper = CreateObject<MmWaveHelper>();
    mmwaveHelper->SetPathlossModelType("ns3::ThreeGppUmiStreetCanyonPropagationLossModel");
    mmwaveHelper->SetChannelConditionModelType("ns3::ThreeGppUmiStreetCanyonChannelConditionModel");

    Ptr <MmWavePointToPointEpcHelper> epcHelper = CreateObject<MmWavePointToPointEpcHelper>();
    mmwaveHelper->SetEpcHelper(epcHelper);

    GlobalValue::GetValueByName ("N_MmWaveEnbNodes", uintegerValue);
    uint8_t nMmWaveEnbNodes = uintegerValue.Get();
    uint8_t nLteEnbNodes = 1;
    GlobalValue::GetValueByName ("N_Ues", uintegerValue);
    uint32_t ues = uintegerValue.Get();
    uint8_t nUeNodes = ues;
    NS_LOG_INFO(" Bandwidth " << bandwidth << " centerFrequency " << double(centerFrequency)
                                 << " isd_cell " << isd_cell << " numAntennasMcUe " << numAntennasMcUe
                                 << " numAntennasMmWave " << numAntennasMmWave << " nMmWaveEnbNodes "
                                 << unsigned(nMmWaveEnbNodes));
    Ptr <Node> pgw = epcHelper->GetPgwNode();
    NodeContainer remoteHostContainer;
    remoteHostContainer.Create(1);
    Ptr <Node> remoteHost = remoteHostContainer.Get(0);
    InternetStackHelper internet;
    internet.Install(remoteHostContainer);

    PointToPointHelper p2ph;
    p2ph.SetDeviceAttribute("DataRate", DataRateValue(DataRate("100Gb/s")));
    p2ph.SetDeviceAttribute("Mtu", UintegerValue(2500));
    p2ph.SetChannelAttribute("Delay", TimeValue(Seconds(0.010)));
    NetDeviceContainer internetDevices = p2ph.Install(pgw, remoteHost);
    Ipv4AddressHelper ipv4h;
    ipv4h.SetBase("1.0.0.0", "255.0.0.0");
    Ipv4InterfaceContainer internetIpIfaces = ipv4h.Assign(internetDevices);
 
    Ipv4StaticRoutingHelper ipv4RoutingHelper;
    Ptr <Ipv4StaticRouting> remoteHostStaticRouting =
            ipv4RoutingHelper.GetStaticRouting(remoteHost->GetObject<Ipv4>());
    remoteHostStaticRouting->AddNetworkRouteTo(Ipv4Address("7.0.0.0"), Ipv4Mask("255.0.0.0"), 1);
    NodeContainer ueNodes;
    NodeContainer mmWaveEnbNodes;
    NodeContainer lteEnbNodes;
    NodeContainer allEnbNodes;
    mmWaveEnbNodes.Create(nMmWaveEnbNodes);
    lteEnbNodes.Create(nLteEnbNodes);
    ueNodes.Create(nUeNodes);
    allEnbNodes.Add(lteEnbNodes);
    allEnbNodes.Add(mmWaveEnbNodes);

    NodeContainerManager::GetInstance().SetMmWaveEnbNodes(mmWaveEnbNodes);
    Vector centerPosition = Vector(maxXAxis / 2, maxYAxis / 2, 10);
    Ptr <ListPositionAllocator> enbPositionAlloc = CreateObject<ListPositionAllocator>();
    enbPositionAlloc->Add(centerPosition);
    enbPositionAlloc->Add(centerPosition);
    double x, y;
    double nConstellation = nMmWaveEnbNodes - 1;
    for (int8_t i = 0; i < nConstellation; ++i) {
        x = isd_cell * cos((2 * M_PI * i) / (nConstellation));
        y = isd_cell * sin((2 * M_PI * i) / (nConstellation));
        enbPositionAlloc->Add(Vector(centerPosition.x + x, centerPosition.y + y, 10));
    }

    MobilityHelper enbmobility;
    enbmobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    enbmobility.SetPositionAllocator(enbPositionAlloc);
    enbmobility.Install(allEnbNodes);

    MobilityHelper uemobility;

    Ptr <UniformDiscPositionAllocator> uePositionAlloc = CreateObject<UniformDiscPositionAllocator>();

    uePositionAlloc->SetX(centerPosition.x);
    uePositionAlloc->SetY(centerPosition.y);
    uePositionAlloc->SetZ(1.5);

    uePositionAlloc->SetRho(450.0);
    Ptr <UniformRandomVariable> speed = CreateObject<UniformRandomVariable>();

    speed->SetAttribute("Min", DoubleValue(3.0));
    speed->SetAttribute("Max", DoubleValue(7.0));

    uemobility.SetMobilityModel("ns3::RandomWalk2dOutdoorMobilityModel", "Speed",
                                 PointerValue(speed), "Bounds",
                                 RectangleValue(Rectangle(0, maxXAxis, 0, maxYAxis)));
    uemobility.SetPositionAllocator(uePositionAlloc);
    uemobility.Install(ueNodes);
    
    
    // --- START: JAMMER NODE CREATION AND POSITIONING (JAMMER FIX) ---
    // Always created (also when jammerOn=false) so node IDs and random streams are
    // identical in the jammed and in the jammer-free run.
    NodeContainer jammerNode;
    jammerNode.Create(1);
    Ptr<ListPositionAllocator> jammerPositionAlloc = CreateObject<ListPositionAllocator>();
    jammerPositionAlloc->Add(Vector(jammerX, jammerY, jammerZ));
    MobilityHelper jammerMobility;
    jammerMobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    jammerMobility.SetPositionAllocator(jammerPositionAlloc);
    jammerMobility.Install(jammerNode);

    Ptr<ThreeGppUmiStreetCanyonChannelConditionModel> jammerCondModel =
        CreateObject<ThreeGppUmiStreetCanyonChannelConditionModel>();
    jammerCondModel->SetAttribute("UpdatePeriod", TimeValue(MilliSeconds(100)));
    Ptr<ThreeGppUmiStreetCanyonPropagationLossModel> jammerPathLoss =
        CreateObject<ThreeGppUmiStreetCanyonPropagationLossModel>();
    jammerPathLoss->SetAttribute("Frequency", DoubleValue(centerFrequency));
    jammerPathLoss->SetAttribute("ShadowingEnabled", BooleanValue(true));
    jammerPathLoss->SetChannelConditionModel(jammerCondModel);

    if (jammerOn)
    {
        MmWaveEnbPhy::AddJammer(jammerNode.Get(0)->GetObject<MobilityModel>(),
                                jammerPowerDbm,
                                jammerPathLoss);
        NS_LOG_UNCOND("Jammer ON at (" << jammerX << ", " << jammerY << ", " << jammerZ
                                       << ") EIRP " << jammerPowerDbm << " dBm");
    }
    else
    {
        NS_LOG_UNCOND("Jammer OFF (control run)");
    }
    {
        std::ofstream jf("jammer.txt", std::ios_base::out | std::ios_base::trunc);
        jf << "x,y,z,power_dbm,jammer_on,rng_run" << std::endl;
        jf << jammerX << "," << jammerY << "," << jammerZ << "," << jammerPowerDbm << ","
           << (jammerOn ? 1 : 0) << "," << RngSeedManager::GetRun() << std::endl;
    }
    // --- END: JAMMER NODE CREATION AND POSITIONING ---

    double minDistance = 10.0;
    for (uint32_t i = 0; i < ueNodes.GetN(); ++i)
    {
        Ptr<MobilityModel> ueMobility = ueNodes.Get(i)->GetObject<MobilityModel>();
        bool tooClose;
        do
        {
            tooClose = false;
            for (uint32_t j = 0; j < allEnbNodes.GetN(); ++j)
            {
                Ptr<MobilityModel> enbMobility = allEnbNodes.Get(j)->GetObject<MobilityModel>();
                double distance = ueMobility->GetDistanceFrom(enbMobility);
                if (distance < minDistance)
                {
                    ueMobility->SetPosition(uePositionAlloc->GetNext());
                    tooClose = true;
                    break;
                }
            }
        } while (tooClose);
    }

    Config::SetDefault("ns3::MmWaveEnbPhy::TxPower", DoubleValue(44.0));
    Config::SetDefault("ns3::MmWaveEnbPhy::DlSinrWithJammers", BooleanValue(true)); // JAMMER FIX

    NetDeviceContainer lteEnbDevs = mmwaveHelper->InstallLteEnbDevice(lteEnbNodes);
    NetDeviceContainer mmWaveEnbDevs = mmwaveHelper->InstallEnbDevice(mmWaveEnbNodes);
    NetDeviceContainer mcUeDevs = mmwaveHelper->InstallMcUeDevice(ueNodes);


    internet.Install(ueNodes);
    Ipv4InterfaceContainer ueIpIface;
    ueIpIface = epcHelper->AssignUeIpv4Address(NetDeviceContainer(mcUeDevs));
    for (uint32_t u = 0; u < ueNodes.GetN(); ++u) {
        Ptr <Node> ueNode = ueNodes.Get(u);
        Ptr <Ipv4StaticRouting> ueStaticRouting =
                ipv4RoutingHelper.GetStaticRouting(ueNode->GetObject<Ipv4>());
        ueStaticRouting->SetDefaultRoute(epcHelper->GetUeDefaultGatewayAddress(), 1);
    }

    mmwaveHelper->AddX2Interface(lteEnbNodes, mmWaveEnbNodes);
    mmwaveHelper->AttachToClosestEnb(mcUeDevs, mmWaveEnbDevs, lteEnbDevs);

    // --- GET SIMULATION TIME ---
    GlobalValue::GetValueByName ("simTime", doubleValue);
    double simTime = doubleValue.Get ();


    // JAMMER FIX: old McUeNetDevice jammer removed (unattached UE, UE->UE signals are ignored)
    
    





    // JAMMER FIX: antenna bearing block removed (ThreeGppAntennaArrayModel not in ns-3.42)

    int numPrints = simTime / 0.1;


    uint16_t portUdp = 60000;
    Address sinkLocalAddressUdp(InetSocketAddress(Ipv4Address::GetAny(), portUdp));
    PacketSinkHelper sinkHelperUdp("ns3::UdpSocketFactory", sinkLocalAddressUdp);
    ApplicationContainer sinkApp;
    sinkApp.Add(sinkHelperUdp.Install(remoteHost));

    ApplicationContainer clientApp;
    for (uint32_t u = 0; u < ueNodes.GetN(); ++u) {
        PacketSinkHelper dlPacketSinkHelper("ns3::UdpSocketFactory",
                                             InetSocketAddress(Ipv4Address::GetAny(), 1234));
        sinkApp.Add(dlPacketSinkHelper.Install(ueNodes.Get(u)));
        UdpClientHelper dlClient(ueIpIface.GetAddress(u), 1234);
        dlClient.SetAttribute("Interval", TimeValue(MilliSeconds(10)));
        dlClient.SetAttribute("MaxPackets", UintegerValue(UINT32_MAX));
        dlClient.SetAttribute("PacketSize", UintegerValue(100));
        clientApp.Add(dlClient.Install(remoteHost));
    }

    sinkApp.Start (Seconds (0));
    clientApp.Start(MilliSeconds(100));
    clientApp.Stop(Seconds(simTime - 0.1));

    struct timeval time_now{};
    gettimeofday(&time_now, nullptr);
    uint64_t t_startTime_simid = (time_now.tv_sec * 1000) + (time_now.tv_usec / 1000);
    std::string ue_poss_out = "ue_position.txt";
    ClearFile(ue_poss_out, t_startTime_simid);
    ClearFile("enbs.txt", t_startTime_simid);
    ClearFile("gnbs.txt", t_startTime_simid);
    PrintGnuplottableUeListToFile("ues.txt");
    int nodecount = int(NodeList::GetNNodes());
    int UE_iterator = nodecount - int (nUeNodes);
    for (int i = 0; i < numPrints; i++) {
        Simulator::Schedule(Seconds(i * simTime / numPrints), &PrintGnuplottableEnbListToFile, t_startTime_simid);
        for (uint32_t j = 0; j < ueNodes.GetN(); j++) {
            Simulator::Schedule(Seconds(i * simTime / numPrints), &PrintPosition, ueNodes.Get(j),
                                 j + UE_iterator, ue_poss_out, t_startTime_simid);
        }
    }

    if (enableTraces) {
        mmwaveHelper->EnableTraces();
    } else {
        mmwaveHelper->EnableMcTraces(); // JAMMER FIX: writes MmWaveSinrTime.txt (= E2 L3 SINR)
    }

    Ptr <LteHelper> lteHelper = CreateObject<LteHelper>();
    lteHelper->Initialize();
    lteHelper->EnablePhyTraces();
    lteHelper->EnableMacTraces();

    bool run = true;
    if (run) {
        NS_LOG_UNCOND("Simulation time is " << simTime << " seconds ");
        Simulator::Stop(Seconds(simTime));
        NS_LOG_INFO("Run Simulation.");
        Simulator::Run();
    }

    NS_LOG_INFO(lteHelper);
    MmWaveEnbPhy::ClearJammers(); // JAMMER FIX
    Simulator::Destroy();
    NS_LOG_INFO("Done.");
    return 0;
}



