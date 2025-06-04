// TestConsole.cpp : This file contains the 'main' function. Program execution begins and ends there.
//
#include <iostream>
#include <Windows.h>

// Function pointer type
typedef int(__stdcall* ManagedFunctionType)();
typedef bool(__stdcall* initMDL)();
typedef bool(__stdcall* verifyMDL)();

int main()
{

    initMDL currentmDl = NULL;
    verifyMDL verifymDl = NULL;
    HMODULE hModule = LoadLibrary(L"Tap2IDSampleCpp.dll");
    if (!hModule)
    {
        std::cerr << "Failed to load the DLL" << std::endl;
        return 1;
    }



    if (hModule != NULL)
    {

        currentmDl = (initMDL)GetProcAddress(hModule, "initialiseMDL");
        verifymDl = (verifyMDL)GetProcAddress(hModule, "verifyingMDL");
    }

    if (currentmDl != NULL)
    {
        currentmDl();
        printf("\n Init done");

        verifymDl();

    }

    FreeLibrary(hModule);
    return 0;
}