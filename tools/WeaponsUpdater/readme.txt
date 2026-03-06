# This tool is useful for updating weapons values from a new season of Apex Legends to our current capabilities in R5Reloaded.
# Vibe coded by CafeFPS and modified by mkos

# How to use

Step 1.
	Download rsx from: https://github.com/r-ex/rsx/releases/tag/1.0.3  ( or latest ) 

Step 2.
	Load Common(01).rpak using rsx.

Step 3.
	Extract all of type "wepn v1" by clicking a weapon\mp_weapon_*  and choosing "Export" -> "Export all for selected type"

Step 4.
	Run convert_weapons_v3.py 
	Follow the prompts shown on screen

	- It is not advisable to update sounds, choose "no" for this step unless you know what you're doing.
	- Choose "NO" for dropping extended zeros in floats only if the current codebase 
	  already has decimal precision for weapons values. ex: 0.200000

Step 5.

	Make sure to review changes in the output folder before dropping the new weapons files in.
