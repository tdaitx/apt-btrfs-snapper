# Copyright (C) 2011 Canonical
#
# Author:
#  Michael Vogt
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; version 3.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

from __future__ import print_function, unicode_literals

import datetime
import os
import subprocess
import sys
import time
import tempfile


class AptBtrfsSnapshotError(Exception):
    pass


class AptBtrfsNotSupportedError(AptBtrfsSnapshotError):
    pass


class AptBtrfsRootWithNoatimeError(AptBtrfsSnapshotError):
    pass

 


class LowLevelCommands(object):
    """ lowlevel commands invoked to perform various tasks like
        interact with mount and btrfs tools
    """ 
    
    def list(self):
        ret = subprocess.check_output(["snapper", "list"], universal_newlines=True);
        ret = ret.split("\n")
        i = 0; 
        items = []
        for item in ret: 
            i=1+i 
            if i < 3:
                continue;
            split = item.split("|");
            if len(split) > 4: 
                row = {
                    'name' : split[6].strip(),
                    'id' : split[1].strip(),
                    'cleanup' : split[5].strip(),
                    'user_data' : split[7].strip(),
                    'user' : split[4].strip(),
                    'date' : split[3].strip(),
                    'text' : item
                } 
                if row['name'].startswith(AptBtrfsSnapshot.SNAP_PREFIX):
                    items.append(row) 
        return items;
                    
        

    def btrfs_subvolume_snapshot(self, description):
        ret = subprocess.call(["snapper", "create", "-d", description, "-c", "timeline"])
        return ret == 0

    def btrfs_delete_snapshot(self, id):
        ret = subprocess.call(["snapper", "delete", id]) 
        return ret == 0
    
    def btrfs_restore_snapshot(self, id):
        ret = subprocess.call(["snapper", "undochange", id+"..0"])
        return ret == 0;
    
    def btrfs_snapshot_diff(self, id):
        ret = subprocess.check_output(["snapper", "status", id+"..0" ], universal_newlines=True);
        return ret

class AptBtrfsSnapshot(object):
    """ the high level object that interacts with the snapshot system """

    # normal snapshot
    SNAP_PREFIX = "apt-snapper-"
    SNAPPER_TIME = "%a %d %b %Y %I:%M:%S %p %Z"
    # backname when changing
    BACKUP_PREFIX = SNAP_PREFIX + "old-root-"

    def __init__(self): 
        self.commands = LowLevelCommands() 

    def snapshots_supported(self):
        """ verify that the system supports apt btrfs snapshots
            by checking if the right fs layout is used etc
        """
        # check for the helper binary
        return os.path.exists("/usr/bin/snapper")
  

    def _get_now_str(self):
        return datetime.datetime.now().replace(microsecond=0).isoformat(
            str('_'))

    def create_btrfs_root_snapshot(self, additional_prefix=""): 
        snap_id = self._get_now_str()
        name = self.SNAP_PREFIX + additional_prefix + snap_id;
        res = self.commands.btrfs_subvolume_snapshot(name)
        print("Created snapshot with snapper named " + name)
        return res

    def get_btrfs_root_snapshots_list(self, older_than=0, only_id=False):
        """ get the list of available snapshot
            If "older_then" is given (in unixtime format) it will only include
            snapshots that are older then the given date)
        """
        l = []
        if older_than == 0:
            older_than = time.time()
        
        items = self.commands.list()
        for item in items:
            mtime = time.mktime(time.strptime(item['date'], self.SNAPPER_TIME));
            if( older_than > mtime ):
                l.append( item['id'] if only_id else item)
        
        if only_id:
            return l
        
        items = []
        for item in l:
            items.append(item['text'])
        
        return items

    def print_btrfs_root_snapshots(self):
        print("Available snapshots:")
        print("  \n".join(self.get_btrfs_root_snapshots_list()))
        return True

    def _parse_older_than_to_unixtime(self, timefmt):
        now = time.time()
        if not timefmt.endswith("d"):
            raise Exception("Please specify time in days (e.g. 10d)")
        days = int(timefmt[:-1])
        return now - (days * 24 * 60 * 60)

    def print_btrfs_root_snapshots_older_than(self, timefmt):
        older_than_unixtime = self._parse_older_than_to_unixtime(timefmt)
        try:
            print("Available snapshots older than '%s':" % timefmt)
            print("  \n".join(self.get_btrfs_root_snapshots_list(
                older_than=older_than_unixtime)))
        except AptBtrfsRootWithNoatimeError:
            sys.stderr.write("Error: fstab option 'noatime' incompatible "
                             "with option \n")
            return False
        return True

    def clean_btrfs_root_snapshots_older_than(self, timefmt):
        res = True
        older_than_unixtime = self._parse_older_than_to_unixtime(timefmt)
        try:
            for snap in self.get_btrfs_root_snapshots_list(
                    older_than=older_than_unixtime, only_id=True):
                res &= self.delete_snapshot(snap)
        except AptBtrfsRootWithNoatimeError:
            sys.stderr.write("Error: fstab option 'noatime' incompatible with "
                             "option \n")
            return False
        return res
    
    def show_diff(self, snapshot):
        id = self.convert_name_to_id(snapshot)
        
        if id != -1:
            diff = self.commands.btrfs_snapshot_diff(id)
            print(diff)
            return True
        return False
    

    def command_set_default(self, snapshot_name):
        res = self.set_default(snapshot_name)
        return res
    
    def convert_name_to_id(self, snapshot_name):
        id=-1
        snapshot_name = snapshot_name.strip();
        try: 
            int(snapshot_name)
            id=snapshot_name
        except ValueError:  
            list = self.commands.list();
            for item in list:
                if item['name'].strip() == snapshot_name:
                    id=item['id']
                    
        if id == -1:
            sys.stderr.write("Could not find a snapshot with the supplied name or id \n")
                    
        return id;

    def set_default(self, snapshot_name, backup=True):
        """ set new default """
        id = self.convert_name_to_id(snapshot_name)
        
        if id != -1:
            ret = self.commands.btrfs_restore_snapshot(id) 
            return ret
        return False      

    def delete_snapshot(self, snapshot_name): 
        res = self.commands.btrfs_delete_snapshot(snapshot_name)
        return res
