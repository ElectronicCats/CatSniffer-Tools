# Cativity Detector
CativityDetector is a tool designed to analyze channel activity in Zigbee networks. It uses a CatSniffer device to monitor Zigbee channels, captures packets, and displays data related to network activity. The tool also provides graphical representations of the activity, helping users analyze the traffic over various Zigbee channels.

## Installation
To use *CatitivityDetector*, yo must have the required dependencies installed. You can install them with `pip`:
```shell
pip install -r requirements.txt
```
You will also need to connect the CatSniffer device to your computer, as it is the primary hardware used by this tool.

## Usage
You can run the tool via the command line:
```shell
python cativity.py catsniffer_path [options]
```
**Options**:

- **catsniffer**: The serial path to the CatSniffer device. The default path is automatically detected.
- **channel**: The Zigbee channel to start sniffing on. If not provided, the tool will hop through channels 11 to 26.
- **topology**: Show the topology of the network.

> [!NOTE]
> The automatically function may fail in some cases where the operative systems not recognize the vendor ID, and if you have two catnsniffer connected, the first one will be the returned port

### Examples
Run with a automatucally detect catsniffer and hopping channel:
```shell
python cativity.py

  ____      _   _       _ _         ____       _            _             
 / ___|__ _| |_(_)_   _(_) |_ _   _|  _ \  ___| |_ ___  ___| |_ ___  _ __ 
| |   / _` | __| \ \ / / | __| | | | | | |/ _ \ __/ _ \/ __| __/ _ \| '__|
| |__| (_| | |_| |\ V /| | |_| |_| | |_| |  __/ ||  __/ (__| || (_) | |   
 \____\__,_|\__|_| \_/ |_|\__|\__, |____/ \___|\__\___|\___|\__\___/|_|   
                              |___/                                       

A tool to analyze the channel activity fro Zigbee Networks
Author: astrobyte
Version: 1.0


             Channel Activity             
┏━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┓
┃ Current ┃ Channel ┃ Activity ┃ Packets ┃
┡━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━┩
│         │ 11      │          │ 0       │
│         │ 12      │ ❚        │ 1       │
│         │ 13      │          │ 0       │
│         │ 14      │          │ 0       │
│         │ 15      │          │ 0       │
│         │ 16      │          │ 0       │
│         │ 17      │ ❚        │ 1       │
│         │ 18      │          │ 0       │
│         │ 19      │          │ 0       │
│ ---->   │ 20      │          │ 0       │
│         │ 21      │          │ 0       │
│         │ 22      │          │ 0       │
│         │ 23      │          │ 0       │
│         │ 24      │          │ 0       │
│         │ 25      │ ❚❚       │ 2       │
│         │ 26      │ ❚❚       │ 2       │
└─────────┴─────────┴──────────┴─────────┘
         Channel Hopping Activity  
```

Run with a explicit path and fixed channel
```shell
python cativity.py /dev/ttyACM0 --channel 25

  ____      _   _       _ _         ____       _            _             
 / ___|__ _| |_(_)_   _(_) |_ _   _|  _ \  ___| |_ ___  ___| |_ ___  _ __ 
| |   / _` | __| \ \ / / | __| | | | | | |/ _ \ __/ _ \/ __| __/ _ \| '__|
| |__| (_| | |_| |\ V /| | |_| |_| | |_| |  __/ ||  __/ (__| || (_) | |   
 \____\__,_|\__|_| \_/ |_|\__|\__, |____/ \___|\__\___|\___|\__\___/|_|   
                              |___/                                       

A tool to analyze the channel activity fro Zigbee Networks
Author: astrobyte
Version: 1.0


             Channel Activity             
┏━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┓
┃ Current ┃ Channel ┃ Activity ┃ Packets ┃
┡━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━┩
│ ---->   │ 25      │ ❚❚       │ 2       │
└─────────┴─────────┴──────────┴─────────┘
         Channel Hopping Activity 
```

Run a topology recognize
```shell
python cativity.py /dev/ttyACM0 --channel 25 --topology

  ____      _   _       _ _         ____       _            _             
 / ___|__ _| |_(_)_   _(_) |_ _   _|  _ \  ___| |_ ___  ___| |_ ___  _ __ 
| |   / _` | __| \ \ / / | __| | | | | | |/ _ \ __/ _ \/ __| __/ _ \| '__|
| |__| (_| | |_| |\ V /| | |_| |_| | |_| |  __/ ||  __/ (__| || (_) | |   
 \____\__,_|\__|_| \_/ |_|\__|\__, |____/ \___|\__\___|\___|\__\___/|_|   
                              |___/                                       

A tool to analyze the channel activity fro Zigbee Networks
Author: astrobyte
Version: 1.0
         Network Topology - 0         
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Children ┃ Ext. Source             ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 0x3fba   │ 74:4d:bd:ff:fe:60:30:fd │
└──────────┴─────────────────────────┘
       Zigbee Network Topology 
```

## Functionality
- Sniffing Zigbee Channels: The tool listens to Zigbee channels (11 to 26) and collects packet data. It can either hop between channels automatically or remain fixed on a user-specified channel.
- Channel Hopping: The tool hops between Zigbee channels with a default interval of 3.5 seconds. It collects and analyzes packet data for each channel.
- Data Collection: As packets are received, the tool processes them using the Sniffer class, which decodes the Zigbee frames. It uses the TISnifferPacket class to handle packet payloads.
- Graphing Activity: The tool visualizes the channel activity using the Graphs class. It continuously updates the graph based on the number of packets received for each channel.
- Topology: Show the network childs of the network as the packet will be detected.
- Threading: The tool runs two background threads:
  - One for handling the channel hopping and activity collection.
  - One for updating and displaying the graphical representation of the channel activity.
- Logging: The tool logs key events and errors to both the console and a log file (catbee.log). The default logging level is set to "WARNING", but this can be adjusted in the logging configuration.

# Acknowledgements
Special thanks to @kevlem97 for the catbee repository, which served as the foundation for this project.