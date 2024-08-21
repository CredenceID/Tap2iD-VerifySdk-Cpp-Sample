#include "pch.h"
#include "AccessTest.h"


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

public ref class mDLInterface
{
public:

    static bool initMDL()
    {
		bool returnValue = false;

		tap2idVerifier = VerifyMdocFactory::CreateVerifyMdoc() ;

		CoreSdkConfig^ currentConfig = gcnew CoreSdkConfig();
		currentConfig->ApiKey = "";

		Task <Tap2iDResultError>^ initTask = dynamic_cast<Task <Tap2iDResultError>^>(tap2idVerifier->InitTap2iDAsync(currentConfig));
		initTask->Wait();

		try
		{
			if (initTask->Result == Tap2iDResultError::OK)
			{
				verifyDelegate = gcnew DelegateVerifyState();
				verifyDelegate->OnVerifyState = gcnew OnVerifyState(&currentVeriyfyState);
				currentMdocConfig = gcnew MdocConfig();
				currentMdocConfig->DeviceEngagementString = "mdoc:owBjMS4wAYIB2BhYS6QBAiABIVggOIuLk-mBsB2LhEzbgVD4J5LDhRgMirIsw4t8dLsJlEIiWCDnHnl6HJXv3HmzahYQBE0b4OGsmKEP4HdLtiNWQBM1BQKBgwIBowD0AfULUC1kt8pjR0qGpsFWjZORpQc";
				CIdentity^ identity = gcnew CIdentity();
				
				Task <Tap2iDResult^>^ verifyTask = tap2idVerifier->VerifyMdocAsync(currentMdocConfig, verifyDelegate);
				verifyTask->Wait();
				Tap2iDResult^ verifyResult = verifyTask->Result;
				returnValue = (verifyResult->ResultError == Tap2iDResultError::OK);
			}
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