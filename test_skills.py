import time
import logging
import os
from skills import (
    tell_time,
    tell_date,
    get_weather,
    search_web,
    take_screenshot,
    open_website,
    run_command,
    set_volume,
    open_app,
    set_reminder,
    get_news_briefing,
    play_music,
    read_emails,
    run_python_file,
    summarize_file,
    smart_home,
    system_report,
    set_alarm,
    route_intent
)

# Configure basic logging to see skill execution traces
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def run_tests():
    print("==================================================")
    print("          JARVIS SKILLS VERIFICATION SUITE        ")
    print("==================================================")
    
    # 1. Test Date & Time (read-only)
    print("\n--- Test 1: Date & Time ---")
    time_result = tell_time()
    date_result = tell_date()
    print("tell_time() ->", time_result)
    print("tell_date() ->", date_result)
    
    # 2. Test Weather (Network call to wttr.in)
    print("\n--- Test 2: Weather (London & Auto) ---")
    weather_london = get_weather("London")
    print("get_weather('London') ->", weather_london)
    weather_auto = get_weather("auto")
    print("get_weather('auto')   ->", weather_auto)
    
    # 3. Test Web Search (Network call to DuckDuckGo)
    print("\n--- Test 3: DuckDuckGo Web Search ---")
    search_result = search_web("What is Python programming")
    print("search_web('What is Python programming') ->", search_result)
    
    # 4. Test Website Opener (Opens default browser)
    print("\n--- Test 4: Open website ---")
    site_result = open_website("youtube")
    print("open_website('youtube') ->", site_result)
    
    # 5. Test Command Executor (Captures cmd outputs)
    print("\n--- Test 5: Command Execution ---")
    cmd_result = run_command("echo Hello from JARVIS skills test")
    print("run_command('echo Hello...') ->", cmd_result)
    
    # 6. Test Screenshot Capture (Saves to Desktop)
    print("\n--- Test 6: Screenshot Capture ---")
    screenshot_result = take_screenshot()
    print("take_screenshot() ->", screenshot_result)
    
    # 7. Test Application Launcher (Launches Notepad)
    print("\n--- Test 7: Application Launcher ---")
    app_result = open_app("notepad")
    print("open_app('notepad') ->", app_result)
    
    # 8. Test Volume Adjustment (Turns volume down 20%)
    print("\n--- Test 8: Volume Adjustment ---")
    volume_result = set_volume(-2)  # Decreases volume by 20%
    print("set_volume(-2) ->", volume_result)
    
    # 9. Test Reminder Setup (Schedules a Windows Task)
    print("\n--- Test 9: Reminder Task Scheduler ---")
    reminder_result = set_reminder("Drink some water, sir", 1)  # 1 minute from now
    print("set_reminder('Drink some water, sir', 1) ->", reminder_result)

    # 10. Test News Briefing (BBC RSS)
    print("\n--- Test 10: News Briefing ---")
    news_result = get_news_briefing()
    print("get_news_briefing() ->", news_result)

    # 11. Test Music Playback
    print("\n--- Test 11: Play Music ---")
    music_result = play_music("stairway to heaven")
    print("play_music('stairway to heaven') ->", music_result)

    # 12. Test Email Reading
    print("\n--- Test 12: Read Emails ---")
    email_result = read_emails(3)
    print("read_emails(3) ->", email_result)

    # 13. Test Run Python File
    print("\n--- Test 13: Run Python File ---")
    dummy_script = "dummy_test.py"
    with open(dummy_script, "w") as f:
        f.write("print('Hello from dummy script, sir.')\n")
    try:
        python_result = run_python_file(dummy_script)
        print(f"run_python_file('{dummy_script}') ->", python_result)
    finally:
        if os.path.exists(dummy_script):
            os.remove(dummy_script)

    # 14. Test File Summarization
    print("\n--- Test 14: Summarize File ---")
    summary_result = summarize_file("README.md")
    print("summarize_file('README.md') ->", summary_result)

    # 15. Test Smart Home REST call
    print("\n--- Test 15: Smart Home Control ---")
    sh_result = smart_home("light.living_room", "on")
    print("smart_home('light.living_room', 'on') ->", sh_result)

    # 16. Test System Diagnostics Report
    print("\n--- Test 16: System Diagnostics Report ---")
    sys_result = system_report()
    print("system_report() ->", sys_result)

    # 17. Test Alarm Scheduler
    print("\n--- Test 17: Alarm Scheduler ---")
    alarm_result = set_alarm("7:30 AM")
    print("set_alarm('7:30 AM') ->", alarm_result)

    # 18. Test Intent Router (Keyword Matching for all skills)
    print("\n--- Test 18: Intent Router (Keywords) ---")
    phrases = [
        "what time is it?",
        "tell me the date please",
        "open calculator",
        "turn up the volume",
        "weather in Tokyo",
        "remind me to check the oven in 5 minutes",
        "what is the news today?",
        "play bohemian rhapsody by queen",
        "check my unread emails",
        "run python script test_skills.py",
        "summarize text file README.md",
        "turn off living room light",
        "give me a system report",
        "set alarm for 6:30 am"
    ]
    for p in phrases:
        func, params = route_intent(p)
        print(f"Query: '{p}' -> Skill: {func.__name__ if func else 'None'}, Params: {params}")

if __name__ == "__main__":
    run_tests()
