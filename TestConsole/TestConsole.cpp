// TestConsole.cpp : This file contains the 'main' function. Program execution begins and ends there.
//
#include <iostream>
#include <Windows.h>

// Function pointer type
typedef int(__stdcall* ManagedFunctionType)();
typedef bool(__stdcall* initMDL)();

int main()
{

    initMDL currentmDl = NULL;
    HMODULE hModule = LoadLibrary(L"AccessTest.dll");
    if (!hModule)
    {
        std::cerr << "Failed to load the DLL" << std::endl;
        return 1;
    }



    if (hModule != NULL)
    {

        currentmDl = (initMDL)GetProcAddress(hModule, "initialiseMDL");
    }

    if (currentmDl != NULL)
    {
        currentmDl();

        printf("\n And Here");
    }

    FreeLibrary(hModule);
    return 0;
}