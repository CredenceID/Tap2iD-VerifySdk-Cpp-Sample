# Tap2iDSDK Solution Overview

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
- **Logging.dll, Serilog.dll, Serilog.Sinks.File.dll**: Logging libraries that write logs to a local file in debug versions (C:\Users\<username>\AppData\Local\Packages\7b2f0efe-eaab-46f6-8e5e-e85b59e554d2_zzh97mbznj2x8\LocalCache\Local).
- **C.identity.dll**: The core Credence library that handles mDoc verification.
- **cbor.dll**: A library for CBOR decoding.
- **io.reactivex.rxjava2.dll**: The RxJava library for reactive programming.
- **org.bouncycastle.pkix.dll, org.bouncycastle.provider.dll**: Bouncy Castle Crypto libraries, a Java implementation of cryptographic algorithms.
- **Microsoft.Windows.SDK.NET.dll**: Provides the .NET bindings to access WinRT APIs used by WinUI.
- **Microsoft.CSharp.dll**: Contains the C# runtime binder, essential for dynamic features in C#.
- **IKVM.Runtime.dll, IKVM.Java.dll, IKVM.ByteCode.dll**: Part of the IKVM.NET suite, which allows Java to run on .NET.
  - **IKVM Dependencies**:
    - IKVM folder for the appropriate platform (e.g., `win-x64`).
    - `ikvm.properties`: Configures the path to the IKVM root folder.
    - **Microsoft.Extensions.DependencyModel.dll**: Provides access to .NET Core's dependency model.
    - **System.Data.Odbc.dll**: Provides support for ODBC data sources in .NET.
- **WinRT.Runtime.dll**: Part of the WinRT (Windows Runtime) infrastructure, enabling .NET to interact with WinRT components.


