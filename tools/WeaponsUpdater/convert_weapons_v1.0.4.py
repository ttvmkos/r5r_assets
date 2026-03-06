import os
import re
import argparse
from collections import OrderedDict
import sys
import shutil

try:
    import pyperclip
except ImportError:
    pyperclip = None

try:
    import tkinter as tk
    import tkinter.messagebox as messagebox
except ImportError:
    print("Error: tkinter is not installed.")
    print("tkinter is required for the GUI input functionality.")
    print("To install tkinter, please follow the instructions below:")
    print("  - On Ubuntu/Debian: run 'sudo apt-get install python3-tk'")
    print("  - On Fedora: run 'sudo dnf install python3-tkinter'")
    print("  - On Windows: tkinter usually comes with the standard Python installation. Ensure you have a full Python distribution installed.")
    sys.exit(1)

# Global flags
UPDATE_WEAPON_SOUNDS = True
DROP_EXTENDED_ZEROS = False
EXCLUSION_KEYS = set()

def load_settings_cache(cache_path):
    """
    Load cached settings from the cache file.
    Expected format is key=value per line.
    """
    if not os.path.isfile(cache_path):
        return None
    try:
        settings = {}
        with open(cache_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and "=" in line:
                    key, value = line.split("=", 1)
                    settings[key.strip()] = value.strip()
        return settings
    except Exception as e:
        print(f"Error loading settings cache: {e}")
        return None

def save_settings_cache(cache_path, settings):
    """
    Save the current settings to the cache file in key=value format.
    """
    try:
        with open(cache_path, "w") as f:
            for key, value in settings.items():
                f.write(f"{key}={value}\n")
    except Exception as e:
        print(f"Error saving settings cache: {e}")

def enhanced_clipboard_input(prompt):
    """
    Custom GUI input function that lets you either type your input or
    right-click in the entry field to paste clipboard content.
    It checks that the entered text is a single line (i.e. a valid path)
    and will display an error message if not.
    """
    while True:
        root = tk.Tk()
        root.title("Input")
        root.resizable(False, False)
        
        label = tk.Label(root, text=prompt)
        label.pack(padx=10, pady=10)
        
        entry = tk.Entry(root, width=50)
        entry.pack(padx=10, pady=10)
        
        def on_right_click(event):
            try:
                clipboard_content = root.clipboard_get()
            except Exception:
                clipboard_content = ""
            entry.delete(0, tk.END)
            entry.insert(0, clipboard_content)
        
        entry.bind("<Button-3>", on_right_click)
        
        def submit():
            root.quit()
        
        submit_button = tk.Button(root, text="Submit", command=submit)
        submit_button.pack(padx=10, pady=10)
        
        root.mainloop()
        result = entry.get().strip()
        root.destroy()
        
        # Check for multiple lines or empty input (empty not allowed here)
        if "\n" in result:
            error_root = tk.Tk()
            error_root.withdraw()
            messagebox.showerror("Invalid Input", "The pasted content is not a valid single-line path. Please try again.")
            error_root.destroy()
            continue
        if not result:
            error_root = tk.Tk()
            error_root.withdraw()
            messagebox.showerror("Invalid Input", "The input cannot be empty. Please try again.")
            error_root.destroy()
            continue
        
        return result

def enhanced_clipboard_input_with_default(prompt, default):
    """
    Similar to enhanced_clipboard_input, but if the input is empty,
    it returns the provided default value.
    """
    while True:
        root = tk.Tk()
        root.title("Input")
        root.resizable(False, False)
        
        label = tk.Label(root, text=prompt)
        label.pack(padx=10, pady=10)
        
        entry = tk.Entry(root, width=50)
        entry.pack(padx=10, pady=10)
        
        def on_right_click(event):
            try:
                clipboard_content = root.clipboard_get()
            except Exception:
                clipboard_content = ""
            entry.delete(0, tk.END)
            entry.insert(0, clipboard_content)
        
        entry.bind("<Button-3>", on_right_click)
        
        def submit():
            root.quit()
        
        submit_button = tk.Button(root, text="Submit", command=submit)
        submit_button.pack(padx=10, pady=10)
        
        root.mainloop()
        result = entry.get().strip()
        root.destroy()
        
        # Check for multiple lines
        if "\n" in result:
            error_root = tk.Tk()
            error_root.withdraw()
            messagebox.showerror("Invalid Input", "The pasted content is not a valid single-line path. Please try again.")
            error_root.destroy()
            continue
        
        # If empty, return the default
        if not result:
            return default
        
        return result

def parse_weapon_data(content):
    weapon_data = OrderedDict()
    in_weapon_data = False
    weapon_section_ended = False
    lines = content.split("\n")
    
    for line in lines:
        stripped = line.strip()
        
        # Detect both "WeaponData" and WeaponData (unquoted)
        if stripped.lower() in ['"weapondata"', "weapondata"]:
            in_weapon_data = True
            continue
            
        if in_weapon_data and not weapon_section_ended:
            # Check for special sections that would terminate the weapon data section
            if any(stripped.lower().startswith(section.lower()) for section in 
                  ['"mods"', "mods", '"pve_base"', "pve_base"]):
                weapon_section_ended = True
                continue
                
            if stripped.startswith("//"):
                continue
                
            # Handle lines with/without opening braces
            if stripped == "{":
                continue  # Skip opening brace
            if stripped == "}":
                weapon_section_ended = True  # End of WeaponData block
                continue
                
            # Improved regex to capture key/value pairs
            match = re.match(r'^\s*"?([^"]+)"?\s+"?([^"]+)"?\s*$', stripped)
            if match:
                key = match.group(1).strip().strip('"')
                value = match.group(2).strip().strip('"')
                weapon_data[key] = value
                
    return weapon_data

def should_skip_key(key):
    # Global update flag for weapon sounds
    global UPDATE_WEAPON_SOUNDS
    
    if not UPDATE_WEAPON_SOUNDS and re.search(r'(_sound|sound_)', key):
        return True
    
    # Regex patterns for excluded keys
    exclusion_patterns = [
        r"^OnWeapon",
        r"^OnProjectile", 
        r"^bodygroup\d+_name$",
        r"^bodygroup\d+_set$",
        r"^ui\d+_enable$",
        r"^ui\d+_draw_cloaked$"
    ]
      
    for pattern in exclusion_patterns:
        if re.match(pattern, key):
            return True

    if key in EXCLUSION_KEYS:
        return True
        
    return False

def convert_to_signed_32(value_str):
    """
    If the given value_str represents an integer (and not a float)
    that is beyond the 32-bit signed integer range, perform a conversion.
    Otherwise, return the original string.
    """
    # Check if it is a simple integer (optional sign followed by digits)
    if not re.fullmatch(r'-?\d+', value_str):
        return value_str
    try:
        num = int(value_str)
    except Exception:
        return value_str

    # If it's already within the 32-bit signed integer range, return as is.
    if -2147483648 <= num <= 2147483647:
        return value_str

    # Otherwise, perform conversion to a 32-bit signed integer.
    converted = num & 0xFFFFFFFF
    if converted >= 0x80000000:
        converted = converted - 0x100000000
    return str(converted)

def process_folders(old_folder, updated_folder, output_folder, add_new_values=True):
    FORCE_ADD_KEYS = {
        "headshot_distance", 
        "damage_headshot_scale",
        "damage_leg_scale",
        "damage_shield_scale",
        "critical_hit",
        "critical_hit_damage_scale",
        "titanarmor_critical_hit_required",
        "damage_near_distance",
        "damage_far_distance",
        "damage_very_far_distance"
    }
    
    # Define sections that can come before mods block
    SPECIAL_SECTIONS = [
        "mods",
        '"mods"',
        "PVE_BASE",
        '"PVE_BASE"',
        # Add any additional sections here that might appear before mods
    ]
    
    os.makedirs(output_folder, exist_ok=True)
    weapons_output_folder = os.path.join(output_folder, "weapons")
    os.makedirs(weapons_output_folder, exist_ok=True)
    
    # Prepare the summary log list
    summary_lines = []
    
    try:
        old_files = set(os.listdir(old_folder))
    except Exception as e:
        msg = f"Error reading directory {old_folder}: {e}"
        print(msg)
        summary_lines.append(msg)
        return summary_lines

    try:
        updated_files = set(os.listdir(updated_folder))
    except Exception as e:
        msg = f"Error reading directory {updated_folder}: {e}"
        print(msg)
        summary_lines.append(msg)
        return summary_lines

    common_files = old_files & updated_files

    if not common_files:
        msg = "No common files found between the provided directories."
        print(msg)
        summary_lines.append(msg)
        return summary_lines

    for filename in common_files:
        file_summary = []
        file_summary.append("\n" + "=" * 40)
        file_summary.append(f"Processing: {filename}")
        file_summary.append("=" * 40)
        print(f"\n{'=' * 40}\nProcessing: {filename}\n{'=' * 40}")
        
        old_path = os.path.join(old_folder, filename)
        updated_path = os.path.join(updated_folder, filename)
        output_path = os.path.join(weapons_output_folder, filename)

        # Read and parse files
        try:
            with open(old_path, "r") as f:
                old_lines = f.readlines()
                old_content = "".join(old_lines)
        except Exception as e:
            err_msg = f"Error reading file {old_path}: {e}"
            print(err_msg)
            file_summary.append(err_msg)
            summary_lines.extend(file_summary)
            continue

        try:
            with open(updated_path, "r") as f:
                updated_content = f.read()
                updated_data = parse_weapon_data(updated_content)
        except Exception as e:
            err_msg = f"Error reading file {updated_path}: {e}"
            print(err_msg)
            file_summary.append(err_msg)
            summary_lines.extend(file_summary)
            continue

        # Track changes
        changes_made = False
        added_keys = set()
        in_weapon_data = False
        in_special_section = False
        output_lines = []
        weapon_data_end = None
        section_start = None

        # Parse old data for later comparison
        old_data = parse_weapon_data(old_content)
        
        for i, line in enumerate(old_lines):
            stripped = line.strip()
            
            # Detect WeaponData block start
            if not in_weapon_data and not in_special_section:
                if stripped.lower() in ["weapondata", '"weapondata"']:
                    in_weapon_data = True
                    output_lines.append(line)
                    continue
                output_lines.append(line)
                continue

            # Check for special sections within WeaponData
            if in_weapon_data and not in_special_section:
                # Check if the line starts with any special section
                for section in SPECIAL_SECTIONS:
                    if stripped.lower().startswith(section.lower()):
                        # Set insertion point right before this section
                        section_start = len(output_lines)
                        output_lines.append(line)
                        in_special_section = True
                        break
                
                # If we've found a special section, continue to the next line
                if in_special_section:
                    continue

            # Check for closing brace of WeaponData block
            if in_weapon_data and not in_special_section and stripped == "}":
                # Save this as the insertion point if no special section was found
                if section_start is None:
                    weapon_data_end = len(output_lines)
                output_lines.append(line)
                in_weapon_data = False
                continue
                
            # Process WeaponData lines
            if in_weapon_data and not in_special_section:
                match = re.match(r'^(\s*)"([^"]+)"(\s+)"([^"]*)"', line)
                if match:
                    indent = match.group(1)
                    key = match.group(2)
                    spacing = match.group(3)
                    value = match.group(4)

                    # Update existing values if key exists in updated_data and should not be skipped
                    if key in updated_data and not should_skip_key(key):
                        new_value = updated_data[key]
                        converted_new_value = convert_to_signed_32(new_value)
                        
                        # If dropping extended zeros in floats, compare numerically if possible
                        if DROP_EXTENDED_ZEROS:
                            try:
                                if float(value) == float(converted_new_value):
                                    output_lines.append(line)
                                    continue
                            except Exception:
                                pass
                        
                        if converted_new_value != value:
                            new_line = f'{indent}"{key}"{spacing}"{converted_new_value}"\n'
                            output_lines.append(new_line)
                            changes_made = True
                            continue
                    
                    # Preserve original line
                    output_lines.append(line)
                else:
                    # Preserve comments and empty lines
                    output_lines.append(line)
            else:
                # Add any lines that are not in the WeaponData section or are in special sections
                output_lines.append(line)

        # Add new keys before special section or closing brace
        if add_new_values or FORCE_ADD_KEYS:
            new_entries = []
            for key in updated_data:
                if key not in added_keys and key not in old_data and (key in FORCE_ADD_KEYS or add_new_values) and not should_skip_key(key):
                    value_converted = convert_to_signed_32(updated_data[key])
                    new_entries.append(f'\t"{key}"\t"{value_converted}"')
                    added_keys.add(key)

            if new_entries:
                changes_made = True
                
                # Choose insertion point: prefer before special section, fall back to before closing brace
                insert_at = section_start if section_start is not None else weapon_data_end
                
                if insert_at is None:
                    # Fallback if neither special section nor closing brace was found
                    insert_at = len(output_lines)
                
                # Add empty line before new entries if needed
                if insert_at > 0 and not output_lines[insert_at - 1].strip().startswith(("//", "#")):
                    new_entries.insert(0, "")
                
                # Insert new entries in reverse order to maintain the correct order
                for entry in reversed(new_entries):
                    output_lines.insert(insert_at, entry + "\n")

        # Write output if changes were made
        if changes_made:
            try:
                with open(output_path, "w") as f:
                    f.writelines(output_lines)
                msg = f"Successfully updated {filename}"
                print(msg)
                file_summary.append(msg)
                file_summary.append("Changes made:")
                file_summary.append("-" * 40)
                for key in updated_data:
                    if key in old_data:
                        old_val = old_data[key]
                        new_val = convert_to_signed_32(updated_data[key])
                        if DROP_EXTENDED_ZEROS:
                            try:
                                if float(old_val) == float(new_val):
                                    continue
                            except Exception:
                                pass
                        if new_val != old_val and not should_skip_key(key):
                            change_line = f"  {key}: {old_val} → {new_val}"
                            print(change_line)
                            file_summary.append(change_line)
                if added_keys:
                    file_summary.append("")
                    file_summary.append("Added keys:")
                    for key in added_keys:
                        added_line = f"  {key}: {convert_to_signed_32(updated_data[key])}"
                        print(added_line)
                        file_summary.append(added_line)
            except Exception as e:
                err_msg = f"Error writing to file {output_path}: {e}"
                print(err_msg)
                file_summary.append(err_msg)
        else:
            msg = "No changes required"
            print(msg)
            file_summary.append(msg)

        print("=" * 40)
        summary_lines.extend(file_summary)

    # Write summary log to file with UTF-8 encoding to support special characters
    summary_path = os.path.join(output_folder, "change_summary.txt")
    try:
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("\n".join(summary_lines))
        print(f"\nChange summary written to: {summary_path}")
    except Exception as e:
        print(f"Error writing change summary: {e}")
    
    return summary_lines

def main():
    # Load exclusion keys from exclusions.txt
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        script_dir = os.getcwd()
    exclusions_file = os.path.join(script_dir, "exclusions.txt")
    global EXCLUSION_KEYS
    if not os.path.isfile(exclusions_file):
        root = tk.Tk()
        root.withdraw()
        proceed = messagebox.askyesno("Exclusions file not found", "Exclusions list for keys was not found. Are you sure you want to continue?")
        root.destroy()
        if not proceed:
            sys.exit(0)
        EXCLUSION_KEYS = set()
    else:
        with open(exclusions_file, "r") as f:
            keys = [line.strip() for line in f if line.strip() and not line.strip().startswith("//")]
        EXCLUSION_KEYS = set(keys)
        
        # Interactive window to manage exclusions
        exclusions_gui = tk.Tk()
        exclusions_gui.geometry("400x300")
        exclusions_gui.title("Manage Exclusion Keys")
        
        list_frame = tk.Frame(exclusions_gui)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        listbox = tk.Listbox(list_frame, selectmode=tk.SINGLE, yscrollcommand=scrollbar.set)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=listbox.yview)
        
        for key in sorted(EXCLUSION_KEYS):
            listbox.insert(tk.END, key)
        
        entry = tk.Entry(exclusions_gui)
        entry.pack(padx=10, pady=10)
        
        def add_key():
            key = entry.get().strip()
            if key and key not in EXCLUSION_KEYS:
                EXCLUSION_KEYS.add(key)
                listbox.insert(tk.END, key)
            entry.delete(0, tk.END)
        
        def remove_key():
            selection = listbox.curselection()
            if selection:
                index = selection[0]
                key = listbox.get(index)
                if key in EXCLUSION_KEYS:
                    EXCLUSION_KEYS.remove(key)
                listbox.delete(index)
        
        button_frame = tk.Frame(exclusions_gui)
        button_frame.pack(pady=10)
        
        add_button = tk.Button(button_frame, text="Add", command=add_key)
        add_button.pack(side=tk.LEFT, padx=5)
        
        remove_button = tk.Button(button_frame, text="Remove", command=remove_key)
        remove_button.pack(side=tk.LEFT, padx=5)
        
        def continue_action():
            exclusions_gui.destroy()
        
        continue_button = tk.Button(button_frame, text="Continue", command=continue_action)
        continue_button.pack(side=tk.LEFT, padx=5)
        
        exclusions_gui.mainloop()
    
    parser = argparse.ArgumentParser(description="Process weapon data files by comparing old and updated folders.")
    parser.add_argument("--old_folder", type=str, help="Directory path to the old folder.")
    parser.add_argument("--updated_folder", type=str, help="Directory path to the updated folder.")
    parser.add_argument("--output_folder", type=str, help="Directory path for the output files. If not provided, defaults to './output'.")
    parser.add_argument("--add_new_values", action="store_true", help="Set flag to add new variables from the updated files.")
    
    args = parser.parse_args()
    
    # Check for cached settings first
    cache_path = os.path.join(os.getcwd(), "settings_cache.txt")
    cached_settings = load_settings_cache(cache_path)
    if cached_settings and os.path.isdir(cached_settings.get("old_folder", "")) and os.path.isdir(cached_settings.get("updated_folder", "")):
        root = tk.Tk()
        root.withdraw()
        use_cache = messagebox.askyesno("Use Cached Settings", "Cached settings found. Do you want to use these settings?")
        root.destroy()
        if use_cache:
            args.old_folder = cached_settings["old_folder"]
            args.updated_folder = cached_settings["updated_folder"]
            args.output_folder = cached_settings.get("output_folder", os.path.join(os.getcwd(), "output"))
    
    # Use enhanced_clipboard_input for old and updated folders if not provided
    if not args.old_folder:
        args.old_folder = enhanced_clipboard_input("Enter path to the current weapons folder that needs updated (or right-click to paste clipboard content): ").strip()
    if not args.updated_folder:
        args.updated_folder = enhanced_clipboard_input("Enter path to the updated folder from rsx (or right-click to paste clipboard content): ").strip()
    default_output = os.path.join(os.getcwd(), "output")
    if not args.output_folder:
        prompt = ("Enter path for the output folder (or right-click to paste clipboard content).\n"
                  f"Leave blank to default to: {default_output}")
        args.output_folder = enhanced_clipboard_input_with_default(prompt, default_output).strip()
    
    # Save current settings to cache
    current_settings = {
        "old_folder": args.old_folder,
        "updated_folder": args.updated_folder,
        "output_folder": args.output_folder
    }
    save_settings_cache(cache_path, current_settings)
    
    if not os.path.isdir(args.old_folder):
        print(f"Error: The old folder directory '{args.old_folder}' does not exist or is not a directory.")
        sys.exit(1)
    
    if not os.path.isdir(args.updated_folder):
        print(f"Error: The updated folder directory '{args.updated_folder}' does not exist or is not a directory.")
        sys.exit(1)
    
    # Check if the output folder exists. If it does, notify the user that it will be wiped clean.
    if os.path.isdir(args.output_folder):
        root = tk.Tk()
        root.withdraw()
        proceed = messagebox.askyesno("Output Folder Exists", "The current output directory will be wiped clean before starting. Do you want to proceed?")
        root.destroy()
        if not proceed:
            sys.exit(0)
        # Wipe the output folder contents
        for filename in os.listdir(args.output_folder):
            file_path = os.path.join(args.output_folder, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print(f"Failed to delete {file_path}. Reason: {e}")
    else:
        try:
            os.makedirs(args.output_folder, exist_ok=True)
        except Exception as e:
            print(f"Error creating output folder '{args.output_folder}': {e}")
            sys.exit(1)
    
    root = tk.Tk()
    root.withdraw()
    update_sounds = messagebox.askyesno("Update Weapon Sounds", "Do you want to update weapon sounds?")
    root.destroy()
    global UPDATE_WEAPON_SOUNDS
    UPDATE_WEAPON_SOUNDS = update_sounds
    
    root = tk.Tk()
    root.withdraw()
    drop_zeros = messagebox.askyesno("Drop Extended Zeros", "Do you want to drop extended zeros in floats?")
    root.destroy()
    global DROP_EXTENDED_ZEROS
    DROP_EXTENDED_ZEROS = drop_zeros
    
    process_folders(
        old_folder=args.old_folder,
        updated_folder=args.updated_folder,
        output_folder=args.output_folder,
        add_new_values=args.add_new_values
    )
    
    input("\nProcessing complete. Press Enter to exit...")

if __name__ == "__main__":
    main()