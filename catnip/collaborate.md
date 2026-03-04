# Contributor's Guide - Adding New Features

This guide provides the necessary instructions for adding new functionalities to the CatSniffer Tools project.

---

## Table of Contents

- [Contributor's Guide - Adding New Features](#contributors-guide---adding-new-features)
  - [Table of Contents](#table-of-contents)
  - [Project Structure](#project-structure)
  - [Feature Types](#feature-types)
  - [Adding a New CLI Command](#adding-a-new-cli-command)
    - [Step 1: Define the command in `cli.py`](#step-1-define-the-command-in-clipy)
    - [Step 2: Add subcommands (optional)](#step-2-add-subcommands-optional)
    - [Step 3: Integrate with the device detection system](#step-3-integrate-with-the-device-detection-system)
  - [Adding a New Sniffing Protocol](#adding-a-new-sniffing-protocol)
    - [Step 1: Create the protocol driver](#step-1-create-the-protocol-driver)
    - [Step 2: Integrate with the sniffing system](#step-2-integrate-with-the-sniffing-system)
    - [Step 3: BLE/VHCI Support (If applicable)](#step-3-blevhci-support-if-applicable)
    - [Step 4: Add Wireshark support (optional)](#step-4-add-wireshark-support-optional)
  - [Adding a New Submodule](#adding-a-new-submodule)
    - [Step 1: Create the submodule structure](#step-1-create-the-submodule-structure)
    - [Step 2: Define `__init__.py`](#step-2-define-__init__py)
    - [Step 3: Implement the main class](#step-3-implement-the-main-class)
    - [Step 4: Add CLI commands](#step-4-add-cli-commands)
  - [Adding New Firmware](#adding-new-firmware)
    - [Step 1: Add firmware metadata](#step-1-add-firmware-metadata)
    - [Step 2: Configure Firmware ID (NVS Metadata)](#step-2-configure-firmware-id-nvs-metadata)
    - [Step 3: Add aliases (optional)](#step-3-add-aliases-optional)
  - [Adding Flashing Commands](#adding-flashing-commands)
    - [Modify the `flash` group in `cli.py`](#modify-the-flash-group-in-clipy)
  - [Code Standards](#code-standards)
    - [Code Style](#code-style)
    - [Class Structure](#class-structure)
    - [Login](#login)
    - [Error Handling](#error-handling)
  - [Testing](#testing)
    - [Test Structure](#test-structure)
    - [Writing Tests](#writing-tests)
    - [Running Tests](#running-tests)
    - [Testing Best Practices](#testing-best-practices)
  - [Documentation](#documentation)
    - [Document New Commands](#document-new-commands)
    - [Update README.md](#update-readmemd)
    - [Add to This Guide](#add-to-this-guide)
  - [New Feature Checklist](#new-feature-checklist)
  - [Additional Resources](#additional-resources)
  - [Questions and Support](#questions-and-support)

---

## Project Structure

```catnip/
├── catnip.py                 # Main entry point (CLI)
├── modules/                  # Core application modules
│   ├── cli.py              # Click command and subcommand definitions
│   ├── catnip.py           # CatSniffer hardware detection and management
│   ├── bridge.py           # Serial communication with RP2040 bridge
│   ├── flasher.py          # Firmware management and download (CC1352P7)
│   ├── fw_update.py        # Automatic RP2040 update (UF2)
│   ├── fw_metadata.py      # Firmware ID management in NVS
│   ├── fw_aliases.py       # Alias resolution and official IDs
│   ├── vhci_bridge.py      # Host Controller Interface (HCI) bridge
│   ├── pipes.py            # PCAP pipe management for Wireshark
│   ├── verify.py           # Hardware diagnostic tests
│   ├── cc2538.py           # Flashing driver for TI chips
│   ├── cativity/           # IQ activity monitor (802.15.4)
│   ├── meshtastic/         # Meshtastic protocol tools
│   ├── vhci/               # Protocol implementations over VHCI (BLE)
│   └── sx1262/             # SX1262 radio module (LoRa)
├── protocol/               # Low-level protocol drivers
│   ├── sniffer_ti.py       # Texas Instruments chip (BLE/Zigbee)
│   ├── sniffer_sx.py       # Semtech SX1262 chip (LoRa)
│   └── common.py           # Shared functionality and bases
└── release_v3.1.0.0/       # Local firmware storage
```

---

## Feature Types

Before starting, identify what type of feature you want to add:


| Type | Description | Example |
|------|-------------|---------|
| **New CLI command** | A new main command or subcommand | `catnip.py sniff lora` |
| **New protocol**	| Support for a new wireless protocol | WiFi, Z-Wave, etc. |
| **New submodule** | A new complex tool | Dashboard, analyzer, etc. |
| **New firmware**	| Add new firmware to the system | New Sniffle version |
| **Existing improvement** | Improvements to current features | Decoding enhancements |

---

## Adding a New CLI Command

### Step 1: Define the command in `cli.py`

Commands are defined using Click. Look for the commands section in modules/cli.py:

```python
# Typical command structure
@cli.command('command_name')
@click.option('-d', '--device', type=int, help='Device ID')
@click.option('-o', '--option', type=str, default='value', help='Option description')
def command_name(device, option):
    """Command description that appears in --help"""
    # Your logic here
    click.echo(f"Executing command with device={device}, option={option}")
```

### Step 2: Add subcommands (optional)

For complex commands with multiple subcommands:

```python
@cli.group('command_group')
def group():
    """Group of related commands"""
    pass

@group.command('subcommand1')
def subcommand1():
    """Subcommand description"""
    pass

@group.command('subcommand2')
@click.option('-f', '--flag', is_flag=True, help='An optional flag')
def subcommand2(flag):
    """Another subcommand"""
    pass
```

### Step 3: Integrate with the device detection system

```python
from modules.catnip import CatSniffer

@cli.command('my_command')
@click.option('-d', '--device', type=int, help='Device ID')
def my_command(device):
    """My new command"""
    # Get device instance
    catsniffer = CatSniffer(device_id=device)
    
    # Verify that devices are available
    if not catsniffer.devices:
        click.echo("[-] No CatSniffer devices detected")
        return
    
    # Your logic here
    catsniffer.my_function()
```

---

## Adding a New Sniffing Protocol

### Step 1: Create the protocol driver

Create a new file in protocol/ or extend an existing one:

 ```python
 # protocol/sniffer_new.py
"""
Custom protocol driver
"""
import logging
from protocol.common import SnifferBase

class NewSniffer(SnifferBase):
    """Class to handle the new protocol"""
    
    # Default configuration
    DEFAULT_CHANNEL = 0
    SUPPORTED_CHANNELS = []
    BAUD_RATE = 500000
    
    def __init__(self, port, channel=None):
        super().__init__(port)
        self.channel = channel or self.DEFAULT_CHANNEL
        self.logger = logging.getLogger(__name__)
    
    def configure(self, **kwargs):
        """Configure sniffer parameters"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
    
    def start_capture(self):
        """Start packet capture"""
        self.logger.info(f"Starting capture on channel {self.channel}")
        # Implement start logic
    
    def stop_capture(self):
        """Stop packet capture"""
        self.logger.info("Stopping capture")
        # Implement stop logic
    
    def get_packets(self):
        """Get captured packets"""
        # Implement packet reading
        return []
```

### Step 2: Integrate with the sniffing system

In `modules/cli.py`, add the new command:

```python
@cli.command('sniff')
@click.argument('protocol', type=click.Choice(['ble', 'zigbee', 'lora', 'new']))
@click.option(...)
def sniff(protocol, ...):
    """Command to capture different protocols"""
    if protocol == 'new':
        from protocol.sniffer_new import NewSniffer
        # Initialize and execute using CatSniffer abstraction
        from modules.catnip import catnip_get_device
        device = catnip_get_device()
        sniffer = NewSniffer(device.bridge_port)
        sniffer.start_capture()
```

### Step 3: BLE/VHCI Support (If applicable)

If the protocol is Bluetooth Low Energy or similar using HCI, integrate with modules/vhci/:

```python
# In modules/cli.py
@cli.command('vhci_scan')
def vhci_scan():
    from modules.vhci.bridge import VHCIBridge
    # Scanning logic using the VHCI bridge
    pass
```

### Step 4: Add Wireshark support (optional)

If you want Wireshark integration, extend `modules/pipes.py`:

```
# In modules/pipes.py
def create_new_pipe():
    """Create pipe for the new protocol"""
    # Implement PCAP pipe creation
    pass
```

---

## Adding a New Submodule

### Step 1: Create the submodule structure

```modules/new_module/
├── __init__.py           # Public exports
├── config.py            # Module configuration
├── core.py              # Main logic
├── decoder.py           # Packet decoding
└── ui.py                # User interface (TUI/GUI)
```

### Step 2: Define `__init__.py`

```python
# modules/new_module/__init__.py
"""
New Module - Brief module description
"""

from .core import NewModule
from .decoder import NewDecoder

__all__ = ['NewModule', 'NewDecoder']
```

### Step 3: Implement the main class

```python
# modules/new_module/core.py
import click
import logging

class NewModule:
    """Main class for the new module"""
    
    def __init__(self, device_id=None, **kwargs):
        self.device_id = device_id
        self.logger = logging.getLogger(__name__)
        self.config = kwargs
    
    def start(self):
        """Start the module"""
        self.logger.info("Starting new module")
        # Start logic
    
    def run(self):
        """Run the main function"""
        # Main logic
        pass
    
    def stop(self):
        """Stop the module"""
        self.logger.info("Stopping new module")

```

### Step 4: Add CLI commands

```python
# In modules/cli.py
@cli.group('new')
def new_group():
    """New module tools"""
    pass

@new_group.command('start')
@click.option('-d', '--device', type=int)
@click.option('-v', '--verbose', is_flag=True)
def new_start(device, verbose):
    """Start the new module"""
    from modules.new_module import NewModule
    
    module = NewModule(device_id=device)
    module.start()
    
    try:
        module.run()
    except KeyboardInterrupt:
        module.stop()
```

---

## Adding New Firmware

### Step 1: Add firmware metadata


Official firmwares are managed through a centralized repository. For local testing or adding new support, edit the metadata that the flasher uses to validate and organize files.

Look for where metadata constants are defined (typically queried by `modules/flasher.py` or JSON release files):

```python
# Example entry in FIRMWARE_METADATA
FIRMWARE_METADATA = {
    'new_proto': {
        'filename': 'sniffer_cc1352p7_v1.0.hex',
        'chip': 'CC1352P7',
        'protocol': 'NewProtocol',
        'version': '1.0',
        'description': 'Sniffer for X protocol',
        'sha256': '...' # Optional for validation
    }
}
```

### Step 2: Configure Firmware ID (NVS Metadata)

The CatSniffer uses a metadata system in the RP2040's NVS memory to know which firmware the CC1352P7 has loaded.

1. **Define Official ID**: In `modules/fw_aliases.py`, associate your firmware with a short, unique ID.

2. **Update `fw_metadata.py`**: Ensure the RP2040 shell commands support the new ID if necessary.

### Step 3: Add aliases (optional)

In `modules/fw_aliases.py`, make flashing easier for users with short names:

```python
# In modules/fw_aliases.py
FIRMWARE_ALIASES = {
    'new': 'new_proto',
    'proto-x': 'new_proto',
}
```

---

## Adding Flashing Commands

If you need a specific command to prepare hardware before flashing or perform a post-flash operation:

### Modify the `flash` group in `cli.py`

```python
@cli.group('flash')
def flash():
    """CC1352P7 and RP2040 firmware management"""
    pass

@flash.command('my_special')
@click.argument('file', type=click.Path(exists=True))
def flash_special(file):
    """Perform flashing with special configuration"""
    from modules.cc2538 import CC2538
    # Custom logic using the CC2538 driver
    pass
```

---

## Code Standards

### Code Style

- **Python**: Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/)
- **Naming**: Use `snake_case` for functions and variables, `PascalCase` for classes
- **Docstrings**: Use Google or NumPy format

### Class Structure

```python
class MyClass:
    """Class that does something specific.
    
    More detailed class description if necessary.
    
    Attributes:
        attribute1: Attribute description.
        attribute2: Attribute description.
    """
    
    def __init__(self, param1, param2=None):
        """Initializes the class.
        
        Args:
            param1: Parameter 1 description.
            param2: Parameter 2 description. Defaults to None.
        """
        self.param1 = param1
        self.param2 = param2
    
    def method(self):
        """Method description.
        
        Returns:
            Return type.
        
        Raises:
            Exception: Description of when it's raised.
        """
        pass
```

### Login

Use the `logging` module consistently:

```python
import logging

# Create module-level logger
logger = logging.getLogger(__name__)

# In functions/methods
def my_function():
    logger.debug("Debug message")
    logger.info("Info message")
    logger.warning("Warning")
    logger.error("Error")
    logger.critical("Critical error")
```

### Error Handling

```python
try:
    # Code that might fail
    result = dangerous_operation()
except ValueError as e:
    logger.error(f"Invalid value: {e}")
    raise click.ClickException(f"Error: {e}")
except SerialException as e:
    logger.error(f"Serial communication error: {e}")
    raise click.ClickException("Unable to communicate with device")
```

---

## Testing

### Test Structure

Tests are located in the `tests/` directory:

```
tests/
├── __init__.py
├── conftest.py           # Shared fixtures
├── test_catsniffer.py   # Main module tests
├── test_cativity.py     # Cativity tests
└── test_module.py      # Your new module tests
```

### Writing Tests

```python
# tests/test_new_module.py
import pytest
from modules.new_module import NewModule

class TestNewModule:
    """Tests for the new module"""
    
    @pytest.fixture
    def module(self):
        """Fixture that creates a module instance"""
        return NewModule(device_id=1)
    
    def test_start(self, module):
        """Initialization test"""
        module.start()
        assert module.device_id == 1
    
    def test_run(self, module):
        """Execution test"""
        # Use mock if necessary
        with pytest.mock.patch('builtins.input', return_value='q'):
            module.run()
```

### Running Tests

```bash
# All tests
pytest

# Specific tests
pytest tests/test_module.py

# With coverage
pytest --cov=modules --cov-report=html

# Tests in verbose mode
pytest -v
```

### Testing Best Practices

1. **Naming**: Test names should be descriptive
   1. ✅ `test_sniffer_starts_on_correct_channel`
   2. ❌ `test_sniffer`
2. **Fixtures**: Use fixtures for repeated code
3. **Mocks**: Mock external dependencies (serial, files)
4. **Assertions**: Be specific in assertions
5. **Coverage**: Maintain coverage above 80%

---

## Documentation

### Document New Commands

Add command documentation in `cli.py` using docstrings:

```python
@cli.command('my_command')
@click.option('-o', '--option', help='Option description')
@click.option('-v', '--verbose', is_flag=True, help='Verbose mode')
def my_command(option, verbose):
    """Brief command description.
    
    More detailed description explaining what the command does,
    how to use it, and what results to expect.
    
    Examples:
        $ catnip my_command
        $ catnip my_command --option value
        $ catnip my_command -v -o value
    """
    pass
```

### Update README.md

If you add a significant new feature:

1. Add to the command table
2. Document in the corresponding section
3. Include usage examples

### Add to This Guide

If you add a new type of feature, consider updating this guide with:

- Feature name
- Modified files
- Specific steps
- Code example

---

## New Feature Checklist

Before making a Pull Request, verify:

- [ ] Code follows style standards
- [ ] Tests pass (pytest)
- [ ] Documentation is updated
- [ ] New commands have functional --help
- [ ] Error handling is implemented
- [ ] Logs are used consistently
- [ ] No print statements in production (use logging)
- [ ] External dependencies are documented

---

## Additional Resources

- [Click Documentation](https://click.palletsprojects.com/)
- [PEP 8 Style Guide](https://www.python.org/dev/peps/pep-0008/)
- [Pytest Documentation](https://docs.pytest.org/)
- [Project Documentation](./README.md)

---

## Questions and Support

If you have questions about how to implement a new feature:

1. Review existing examples in the code
2. Check the documentation in README.md
3. Open an issue in the repository to discuss implementation