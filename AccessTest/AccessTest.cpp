#include "pch.h"
#include "AccessTest.h"
using namespace System::Threading;


using namespace System;
using namespace Tap2iDSdk;
using namespace Tap2iDSdk::Model;
using namespace System::Threading::Tasks;

public delegate void   currentVeriyfyDelegate(VerifyState verifiyState);


void currentVeriyfyState(VerifyState verifiyState)
{
	Console::WriteLine("state {0}", verifiyState);
	// Do something with verify state
}

public ref class MyInitSdkResultListener : public Tap2iDSdk::Model::InitSdkResultListener
{
private:
	ManualResetEvent^ initCompleteEvent;
	bool success;
public:
	MyInitSdkResultListener(ManualResetEvent^ event) : initCompleteEvent(event), success(false)
	{
		// Assign event handler methods to the delegate properties
		this->OnInitializationSuccess = gcnew Tap2iDSdk::Model::OnInitializationSuccess(this, &MyInitSdkResultListener::HandleInitializationSuccess);
		this->OnInitializationFailure = gcnew Tap2iDSdk::Model::OnInitializationFailure(this, &MyInitSdkResultListener::HandleInitializationFailure);
	}


	// Event handler for successful initialization
	void HandleInitializationSuccess(SdkInitializationResult^ result)
	{
		Console::WriteLine("Initialization succeeded.");
		success = true;
		initCompleteEvent->Set();  // Signal that initialization is complete
	}

	// Event handler for failed initialization
	void HandleInitializationFailure(Tap2iDResultError error, String^ errorMessage)
	{
		Console::WriteLine("Initialization failed. Error: {0}", errorMessage);
		success = false;
		initCompleteEvent->Set();  // Signal that initialization is complete
	}


	bool IsSuccessful()
	{
		return success;
	}
};

public ref class mDLInterface
{
public:

    static bool initMDL()
    {
		bool returnValue = false;

		tap2idVerifier = VerifyMdocFactory::CreateVerifyMdoc() ;

		CoreSdkConfig^ currentConfig = gcnew CoreSdkConfig();
		currentConfig->ApiKey = "CS364Bew5ettUCPrkOLBRaGI76nnh5YBnx";
		currentConfig->PackageName = "Tap2IdSampleCpp";

		// Create a ManualResetEvent for signaling
		ManualResetEvent^ initCompleteEvent = gcnew ManualResetEvent(false);

		MyInitSdkResultListener^ initlistener = gcnew MyInitSdkResultListener(initCompleteEvent);

		//Task <Tap2iDResultError>^ initTask = dynamic_cast<Task <Tap2iDResultError>^>(tap2idVerifier->InitTap2iDAsync(currentConfig));
		//initTask->Wait();

		tap2idVerifier->InitSdk(currentConfig, initlistener);

		// Wait for the initialization to complete
		initCompleteEvent->WaitOne();

		// Check the success status
		returnValue = initlistener->IsSuccessful();	

		return(returnValue);
    }

	static bool verifyMdl()
	{
		bool returnValue = false;
		try
		{
				verifyDelegate = gcnew DelegateVerifyState();
				verifyDelegate->OnVerifyState = gcnew OnVerifyState(&currentVeriyfyState);
				currentMdocConfig = gcnew MdocConfig();
				currentMdocConfig->DeviceEngagementString = "mdoc:owBjMS4wAYIB2BhYS6QBAiABIVggNvxTuyAwL-S7HL0h8RNgT4NvEz32_yk2cmB5kkctr8kiWCDXqR38c-dD74Lo0sDHkuL2d0IihAsRCLwUxr9yBxgs8AKBgwIBowD0AfULUA_sFipTZkyBhlzg-WY2zhw";
				currentMdocConfig->EngagementMode = DeviceEngagementMode::QrCode;
				currentMdocConfig->BleWriteOption = BleWriteOption::Write;
				CIdentity^ identity = gcnew CIdentity();

				Task <Tap2iDResult^>^ verifyTask = tap2idVerifier->VerifyMdocAsync(currentMdocConfig, verifyDelegate);
				verifyTask->Wait();
				Tap2iDResult^ verifyResult = verifyTask->Result;
				returnValue = (verifyResult->ResultError == Tap2iDResultError::OK);
		}
		catch (AggregateException^ ex)
		{
			for each (Exception ^ innerEx in ex->InnerExceptions)
			{
				Console::WriteLine("Exception: {0}", innerEx->Message);
				if (innerEx->InnerException != nullptr)
				{
					Console::WriteLine("Inner Exception: {0}", innerEx->InnerException->Message);
				}
			}
		}
		return(returnValue);
	}

private:
	static IVerifyMdoc^ tap2idVerifier = nullptr;
	static MdocConfig^ currentMdocConfig = nullptr;
	static DelegateVerifyState^ verifyDelegate = nullptr;
};


extern "C" __declspec(dllexport) bool __stdcall initialiseMDL()
{
	return(mDLInterface::initMDL());

}

extern "C" __declspec(dllexport) bool __stdcall verifyingMDL()
{
	return(mDLInterface::verifyMdl());

}