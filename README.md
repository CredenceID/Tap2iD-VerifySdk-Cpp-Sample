# Tap2iDSampleCpp Solution Overview

## Introduction

This solution is composed of two projects:

1. **AccessTest**  
   This project is a library that utilizes the Tap2iD SDK .NET library.
   It shows how to call the library from c++ and verify a mDoc.
   
3. **TestConsole**  
   This project is a test console application that calls the `AccessTest` library.

## Tap2iDSDK Library and Dependencies

The main entry point is the `Tap2iDSdk.dll`. Below is the list of dependencies for this library:

- **BluetoothWinUI.dll**: A Bluetooth DLL that manages interactions between the Verifier and Wallet.
- **BluetoothBumble.dll, BluetoothBumble.py**: Python script and dll that use bumble stack for bluetooth interaction
- **Logging.dll, Serilog.dll, Serilog.Sinks.File.dll**: Logging libraries that write logs to a local file in debug versions (C:\Users\<username>\Tap2Id).
- **C.identity.dll**: The core Credence library that handles mDoc verification.
- **cbor.dll**: A library for CBOR decoding.
- **device1.json**: Json config file for Bumble Bluetooth
- **io.reactivex.rxjava2.dll**: The RxJava library for reactive programming.
- **org.bouncycastle.pkix.dll, org.bouncycastle.provider.dll**: Bouncy Castle Crypto libraries, a Java implementation of cryptographic algorithms.
- **Microsoft.Windows.SDK.NET.dll**: Provides the .NET bindings to access WinRT APIs used by WinUI.
- **Microsoft.CSharp.dll**: Contains the C# runtime binder, essential for dynamic features in C#.
- **Newtonsoft.Json.dll**: A popular library for handling JSON serialization and deserialization.
- **PCSC.dll, PCSC.Iso7816.dll, PCSC.Reactive.dll**: Provides an interface for smart card communication and management.
- **Python.Runtime.dll**: Integrations of Python functionality
- **System.Management.dll**: Provides access to Windows Management Instrumentation (WMI) resources, allowing applications to query and interact with system information.
- **Tap2iDBluetoothCommon.dll**: A common library to expose interface and utils for Bluetooth
- **IKVM.Runtime.dll, IKVM.Java.dll, IKVM.ByteCode.dll**: Part of the IKVM.NET suite, which allows Java to run on .NET.
  - **IKVM Dependencies**:
    - IKVM folder for the appropriate platform (e.g., `win-x64`).
    - `ikvm.properties`: Configures the path to the IKVM root folder.
    - **Microsoft.Extensions.DependencyModel.dll**: Provides access to .NET Core's dependency model.
    - **System.Text.Encoding.Codepages.dll, System.Text.Encoding.dll,System.Text.Encoding.Extensions.dll, System.Text.Encoding.Web.dll*** : These assemblies collectively enhance the handling of text encoding in .NET applications
    - **System.Data.Odbc.dll**: Provides support for ODBC data sources in .NET.
- **WinRT.Runtime.dll**: Part of the WinRT (Windows Runtime) infrastructure, enabling .NET to interact with WinRT components.
