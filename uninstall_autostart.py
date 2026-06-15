import winreg

def uninstall_autostart():
    """
    Deletes the startup registry entry for JARVIS, disabling auto-run on Windows boot.
    """
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "JARVIS"
    
    try:
        # Open registry key with write permissions
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
        winreg.DeleteValue(key, app_name)
        winreg.CloseKey(key)
        print("Successfully removed JARVIS from Windows startup registry.")
    except FileNotFoundError:
        print("JARVIS was not registered for Windows startup (key not found).")
    except Exception as e:
        print(f"Error removing startup entry: {e}")

if __name__ == "__main__":
    uninstall_autostart()
