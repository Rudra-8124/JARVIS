import os
import sys
import winreg

def setup_autostart():
    """
    Registers JARVIS in the HKEY_CURRENT_USER registry to run at Windows startup
    using pythonw.exe so it runs silently in the background.
    """
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "JARVIS"
    
    # Resolve the absolute path of the current main.py file
    current_dir = os.path.dirname(os.path.abspath(__file__))
    main_py_path = os.path.join(current_dir, "main.py")
    
    # Resolve the path to pythonw.exe within the active virtual environment
    python_exe = sys.executable
    if python_exe.endswith("python.exe"):
        pythonw_exe = python_exe.replace("python.exe", "pythonw.exe")
    elif python_exe.endswith("python3.exe"):
        pythonw_exe = python_exe.replace("python3.exe", "pythonw.exe")
    else:
        # Fallback to general pythonw
        pythonw_exe = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
        
    # Verify files exist before registering
    if not os.path.exists(main_py_path):
        print(f"Error: Could not locate main.py at {main_py_path}")
        return
        
    if not os.path.exists(pythonw_exe):
        # Fallback to standard python.exe path if pythonw.exe is not found
        print("Warning: pythonw.exe not found in environment. Falling back to python.exe")
        pythonw_exe = python_exe

    # Construct the launch command
    command = f'"{pythonw_exe}" "{main_py_path}"'
    
    print(f"Registering startup command: {command}")
    
    try:
        # Open user Run registry key with write access
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
        winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, command)
        winreg.CloseKey(key)
        print("Successfully added JARVIS to Windows startup registry.")
    except Exception as e:
        print(f"Error modifying registry: {e}")

if __name__ == "__main__":
    setup_autostart()
