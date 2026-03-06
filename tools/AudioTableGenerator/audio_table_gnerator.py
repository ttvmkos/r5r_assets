import os
import json
import csv
import time
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


APP_TITLE = "BIK CSV Builder"
BACKUP_FOLDER_NAME = ".bik_csv_tool_backups"


def _now_stamp( ) -> str:
    return time.strftime( "%Y%m%d_%H%M%S" )


def _normalize_rui_location( rui_location: str ) -> str:
    s = ( rui_location or "" ).strip( ).replace( "\\", "/" )
    if s != "" and not s.endswith( "/" ):
        s += "/"
    return s


def _derive_category_from_rui_location( rui_location: str ) -> str:
    s = _normalize_rui_location( rui_location )
    if s == "":
        return ""
    s = s.rstrip( "/" )
    parts = [ p for p in s.split( "/" ) if p != "" ]
    if len( parts ) == 0:
        return ""
    return parts[ -1 ]


def _default_name_from_filename( filename: str ) -> str:
    base = filename
    if base.lower( ).endswith( ".bik" ):
        base = base[ : -4 ]

    idx = base.find( "_" )
    if idx == -1:
        return base

    name = base[ idx + 1 : ]
    if name == "":
        return base
    return name


def _safe_join_urlish( prefix: str, rel_path: str ) -> str:
    p = _normalize_rui_location( prefix )
    r = ( rel_path or "" ).replace( "\\", "/" ).lstrip( "/" )
    return p + r


class EditableTreeview( ttk.Treeview ):
    def __init__( self, master, **kwargs ):
        super( ).__init__( master, **kwargs )
        self._edit_entry = None
        self._edit_info = None

        self.bind( "<Double-1>", self._begin_edit )

    def _begin_edit( self, event ):
        if self._edit_entry is not None:
            return

        region = self.identify( "region", event.x, event.y )
        if region != "cell":
            return

        row_id = self.identify_row( event.y )
        col_id = self.identify_column( event.x )
        if not row_id or not col_id:
            return

        bbox = self.bbox( row_id, col_id )
        if not bbox:
            return

        x, y, w, h = bbox
        col_index = int( col_id.replace( "#", "" ) ) - 1
        columns = self[ "columns" ]
        if col_index < 0 or col_index >= len( columns ):
            return

        column_key = columns[ col_index ]
        current_value = self.set( row_id, column_key )

        self._edit_info = ( row_id, column_key )

        self._edit_entry = ttk.Entry( self )
        self._edit_entry.insert( 0, current_value )
        self._edit_entry.select_range( 0, tk.END )
        self._edit_entry.place( x = x, y = y, width = w, height = h )
        self._edit_entry.focus_set( )

        self._edit_entry.bind( "<Return>", self._commit_edit )
        self._edit_entry.bind( "<Escape>", self._cancel_edit )
        self._edit_entry.bind( "<FocusOut>", self._commit_edit )

    def _commit_edit( self, event = None ):
        if self._edit_entry is None or self._edit_info is None:
            return

        new_value = self._edit_entry.get( )
        row_id, column_key = self._edit_info
        self.set( row_id, column_key, new_value )

        self._edit_entry.destroy( )
        self._edit_entry = None
        self._edit_info = None

        if hasattr( self, "on_cell_edited" ) and callable( getattr( self, "on_cell_edited" ) ):
            self.on_cell_edited( )

    def _cancel_edit( self, event = None ):
        if self._edit_entry is None:
            return

        self._edit_entry.destroy( )
        self._edit_entry = None
        self._edit_info = None


class App( tk.Tk ):
    def __init__( self ):
        super( ).__init__( )
        self.title( APP_TITLE )
        self.geometry( "980x640" )
        self.minsize( 860, 560 )

        self.working_dir_var = tk.StringVar( value = "" )
        self.rui_location_var = tk.StringVar( value = "" )
        self.csv_name_var = tk.StringVar( value = "rui_biks.csv" )
        self.status_var = tk.StringVar( value = "Ready." )

        self.rows = [ ]  # list[ dict{ path, name, category } ]

        self._build_ui( )
        self._try_autoload_backup( )

    def _build_ui( self ):
        root = ttk.Frame( self, padding = 10 )
        root.pack( fill = tk.BOTH, expand = True )

        top = ttk.Frame( root )
        top.pack( fill = tk.X )

        # Working directory
        wd_row = ttk.Frame( top )
        wd_row.pack( fill = tk.X, pady = ( 0, 6 ) )

        ttk.Label( wd_row, text = "Scan Directory:" ).pack( side = tk.LEFT )
        wd_entry = ttk.Entry( wd_row, textvariable = self.working_dir_var )
        wd_entry.pack( side = tk.LEFT, fill = tk.X, expand = True, padx = ( 8, 8 ) )

        ttk.Button( wd_row, text = "Browse...", command = self._browse_working_dir ).pack( side = tk.LEFT )
        ttk.Button( wd_row, text = "Scan .bik", command = self._scan_biks ).pack( side = tk.LEFT, padx = ( 8, 0 ) )

        # Rui location + csv name
        mid_row = ttk.Frame( top )
        mid_row.pack( fill = tk.X, pady = ( 0, 10 ) )

        ttk.Label( mid_row, text = "Rui Location:" ).pack( side = tk.LEFT )
        rui_entry = ttk.Entry( mid_row, textvariable = self.rui_location_var, width = 40 )
        rui_entry.pack( side = tk.LEFT, fill = tk.X, expand = True, padx = ( 8, 16 ) )

        ttk.Label( mid_row, text = "CSV File Name:" ).pack( side = tk.LEFT )
        csv_entry = ttk.Entry( mid_row, textvariable = self.csv_name_var, width = 24 )
        csv_entry.pack( side = tk.LEFT, padx = ( 8, 8 ) )

        ttk.Button( mid_row, text = "Load Backup", command = self._load_backup_dialog ).pack( side = tk.LEFT, padx = ( 0, 8 ) )
        ttk.Button( mid_row, text = "Generate CSV", command = self._generate_csv ).pack( side = tk.LEFT )

        # Table
        table_frame = ttk.Frame( root )
        table_frame.pack( fill = tk.BOTH, expand = True )

        columns = ( "path", "name", "category" )
        self.tree = EditableTreeview(
            table_frame,
            columns = columns,
            show = "headings",
            selectmode = "browse"
        )
        self.tree.heading( "path", text = "path" )
        self.tree.heading( "name", text = "name" )
        self.tree.heading( "category", text = "category" )

        self.tree.column( "path", width = 600, anchor = tk.W )
        self.tree.column( "name", width = 160, anchor = tk.W )
        self.tree.column( "category", width = 160, anchor = tk.W )

        vsb = ttk.Scrollbar( table_frame, orient = "vertical", command = self.tree.yview )
        hsb = ttk.Scrollbar( table_frame, orient = "horizontal", command = self.tree.xview )
        self.tree.configure( yscrollcommand = vsb.set, xscrollcommand = hsb.set )

        self.tree.grid( row = 0, column = 0, sticky = "nsew" )
        vsb.grid( row = 0, column = 1, sticky = "ns" )
        hsb.grid( row = 1, column = 0, sticky = "ew" )

        table_frame.rowconfigure( 0, weight = 1 )
        table_frame.columnconfigure( 0, weight = 1 )

        # Hook edit callback
        self.tree.on_cell_edited = self._on_table_edited

        # Bottom status + controls
        bottom = ttk.Frame( root )
        bottom.pack( fill = tk.X, pady = ( 10, 0 ) )

        ttk.Label( bottom, textvariable = self.status_var ).pack( side = tk.LEFT )

        ttk.Button( bottom, text = "Remove Selected Row", command = self._remove_selected_row ).pack( side = tk.RIGHT )
        ttk.Button( bottom, text = "Save Backup Now", command = self._save_backup ).pack( side = tk.RIGHT, padx = ( 0, 8 ) )

    def _browse_working_dir( self ):
        d = filedialog.askdirectory( title = "Select Working Directory" )
        if d:
            self.working_dir_var.set( d )
            self.status_var.set( f"Working directory set: {d}" )

    def _validate_inputs( self ) -> bool:
        wd = self.working_dir_var.get( ).strip( )
        if wd == "" or not os.path.isdir( wd ):
            messagebox.showerror( "Missing Working Directory", "Please provide a valid working directory." )
            return False

        csv_name = self.csv_name_var.get( ).strip( )
        if csv_name == "":
            messagebox.showerror( "Missing CSV File Name", "Please provide a CSV file name." )
            return False

        if not csv_name.lower( ).endswith( ".csv" ):
            self.csv_name_var.set( csv_name + ".csv" )

        return True

    def _scan_biks( self ):
        if not self._validate_inputs( ):
            return

        wd = self.working_dir_var.get( ).strip( )
        rui_location = self.rui_location_var.get( )
        category = _derive_category_from_rui_location( rui_location )

        bik_files = [ ]
        for root, _, files in os.walk( wd ):
            for f in files:
                if f.lower( ).endswith( ".bik" ):
                    full_path = os.path.join( root, f )
                    bik_files.append( full_path )

        bik_files.sort( key = lambda p: p.lower( ) )

        new_rows = [ ]
        for full_path in bik_files:
            rel_path = os.path.relpath( full_path, wd ).replace( "\\", "/" )
            filename = os.path.basename( full_path )

            row = {
                "path": _safe_join_urlish( rui_location, rel_path ),
                "name": _default_name_from_filename( filename ),
                "category": category
            }
            new_rows.append( row )

        self.rows = new_rows
        self._refresh_table( )

        self.status_var.set( f"Scanned {len( self.rows )} .bik file(s)." )
        self._save_backup( )

    def _refresh_table( self ):
        for item in self.tree.get_children( ):
            self.tree.delete( item )

        for idx, row in enumerate( self.rows ):
            self.tree.insert(
                "",
                tk.END,
                iid = str( idx ),
                values = ( row.get( "path", "" ), row.get( "name", "" ), row.get( "category", "" ) )
            )

    def _sync_rows_from_table( self ):
        synced = [ ]
        for iid in self.tree.get_children( ):
            vals = self.tree.item( iid, "values" )
            if len( vals ) != 3:
                continue
            synced.append( {
                "path": vals[ 0 ],
                "name": vals[ 1 ],
                "category": vals[ 2 ]
            } )
        self.rows = synced

    def _on_table_edited( self ):
        self._sync_rows_from_table( )
        self.status_var.set( "Edited. Backup saved." )
        self._save_backup( )

    def _remove_selected_row( self ):
        sel = self.tree.selection( )
        if not sel:
            return

        iid = sel[ 0 ]
        self.tree.delete( iid )

        self._sync_rows_from_table( )
        self._rebuild_iids( )
        self.status_var.set( "Row removed. Backup saved." )
        self._save_backup( )

    def _rebuild_iids( self ):
        rows = [ ]
        for iid in self.tree.get_children( ):
            vals = self.tree.item( iid, "values" )
            rows.append( vals )

        for iid in self.tree.get_children( ):
            self.tree.delete( iid )

        for i, vals in enumerate( rows ):
            self.tree.insert( "", tk.END, iid = str( i ), values = vals )

    def _backup_dir( self ) -> str:
        tool_dir = os.path.dirname( os.path.abspath( __file__ ) )
        d = os.path.join( tool_dir, BACKUP_FOLDER_NAME )
        os.makedirs( d, exist_ok = True )
        return d

    def _backup_path_latest( self ) -> str:
        csv_name = self.csv_name_var.get( ).strip( )
        base = os.path.splitext( os.path.basename( csv_name ) )[ 0 ]

        tool_dir = os.path.dirname( os.path.abspath( __file__ ) )
        return os.path.join( tool_dir, f"{base}.session.json" )

    def _save_backup( self ):
        if not self._validate_inputs( ):
            return

        self._sync_rows_from_table( )

        payload = {
            "working_dir": self.working_dir_var.get( ).strip( ),
            "rui_location": self.rui_location_var.get( ),
            "csv_name": self.csv_name_var.get( ).strip( ),
            "rows": self.rows
        }

        latest_path = self._backup_path_latest( )
        try:
            with open( latest_path, "w", encoding = "utf-8" ) as f:
                json.dump( payload, f, indent = 2 )

            # Also keep timestamped history copies
            hist_dir = self._backup_dir( )
            hist_path = os.path.join( hist_dir, f"session_{_now_stamp( )}.json" )
            with open( hist_path, "w", encoding = "utf-8" ) as f:
                json.dump( payload, f, indent = 2 )

        except Exception as e:
            messagebox.showwarning( "Backup Failed", f"Failed to save backup:\n{e}" )

    def _try_autoload_backup( self ):
        # If working dir empty, nothing to auto-load
        # Try: if user starts by setting working dir, they can click "Load Backup"
        pass

    def _load_backup_dialog( self ):
        wd = self.working_dir_var.get( ).strip( )
        tool_dir = os.path.dirname( os.path.abspath( __file__ ) )
        initial_dir = tool_dir

        path = filedialog.askopenfilename(
            title = "Load Backup Session",
            initialdir = initial_dir,
            filetypes = [ ( "Session Backup", "*.json" ), ( "All Files", "*.*" ) ]
        )
        if not path:
            return

        self._load_backup_from_path( path )

    def _load_backup_from_path( self, path: str ):
        try:
            with open( path, "r", encoding = "utf-8" ) as f:
                payload = json.load( f )
        except Exception as e:
            messagebox.showerror( "Load Failed", f"Could not read backup:\n{e}" )
            return

        self.working_dir_var.set( payload.get( "working_dir", "" ) )
        self.rui_location_var.set( payload.get( "rui_location", "" ) )
        self.csv_name_var.set( payload.get( "csv_name", "rui_biks.csv" ) )
        self.rows = payload.get( "rows", [ ] )

        self._refresh_table( )
        self.status_var.set( f"Loaded backup: {os.path.basename( path )}" )

    def _generate_csv( self ):
        if not self._validate_inputs( ):
            return

        self._sync_rows_from_table( )

        wd = self.working_dir_var.get( ).strip( )
        csv_name = self.csv_name_var.get( ).strip( )
        tool_dir = os.path.dirname( os.path.abspath( __file__ ) )
        out_path = os.path.join( tool_dir, csv_name )

        # Backup existing CSV if it exists
        try:
            if os.path.isfile( out_path ):
                backup_dir = self._backup_dir( )
                base = os.path.splitext( os.path.basename( out_path ) )[ 0 ]
                bak_path = os.path.join( backup_dir, f"{base}_{_now_stamp( )}.csv.bak" )
                shutil.copy2( out_path, bak_path )
        except Exception as e:
            messagebox.showwarning( "CSV Backup Warning", f"Could not back up existing CSV:\n{e}" )

        # Always save session backup when generating
        self._save_backup( )

        try:
            with open( out_path, "w", newline = "", encoding = "utf-8" ) as f:
                f.write( "path,name,category\n" )

                writer = csv.writer( f, quoting = csv.QUOTE_ALL )
                for row in self.rows:
                    writer.writerow( [
                        row.get( "path", "" ),
                        row.get( "name", "" ),
                        row.get( "category", "" )
                    ] )

                f.write( "string,string,string\n" )

        except Exception as e:
            messagebox.showerror( "Generate Failed", f"Could not write CSV:\n{e}" )
            return

        self.status_var.set( f"Generated CSV: {out_path}" )
        messagebox.showinfo( "Done", f"CSV generated:\n{out_path}" )


if __name__ == "__main__":
    app = App( )
    app.mainloop( )
