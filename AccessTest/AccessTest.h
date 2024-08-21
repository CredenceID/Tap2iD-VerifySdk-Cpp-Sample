#pragma once

using namespace System;

// ManagedLibrary.h
extern "C" __declspec(dllexport) int __stdcall ManagedFunction();
extern "C" __declspec(dllexport) bool __stdcall initMDL();
