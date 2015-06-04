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


class AptBtrfsSnapperError(Exception):
    pass


class AptBtrfsNotSupportedError(AptBtrfsSnapperError):
    pass


class AptBtrfsRootWithNoatimeError(AptBtrfsSnapperError):
    pass

 


class LowLevelCommands(object):
    """ lowlevel commands invoked to perform various tasks like
        interact with mount and btrfs tools
    """
    CLEANUP_MODE='number'
    
    def btrfs_snapshot_list(self):
        ret = subprocess.check_output(["snapper", "list", "-t", "pre-post"], universal_newlines=True)
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
                    'name' : split[4].strip(),
                    'id' : split[1].strip(),
                    'type': 'pre',
                    'cleanup' : self.CLEANUP_MODE,
                    'user_data' : split[5].strip(), 
                    'date' : split[2].strip(),
                    'text' : item,
                    'pre_id' : split[0].strip()
                } 
                if row['name'].startswith(AptBtrfsSnapper.SNAP_PREFIX):
                    items.append(row) 
        return items;
                    
    def btrfs_snapshot_list_pre_post(self):
        ret = subprocess.check_output(["snapper", "list", "-t", "pre-post"], universal_newlines=True);
        lines = ret.split("\n")
        i=0
        out="" 
        for line in lines: 
            if i < 2:
                out+=line + "\n"
                i+=1
            elif AptBtrfsSnapper.SNAP_PREFIX in line:
                out+=line + "\n"
        
        return out

    def btrfs_subvolume_snapshot(self, description, ctype, pre_id="-1"):
        arguments = ["snapper", "create", "-d", description, "-c",
                     self.CLEANUP_MODE, "--print-number", "-t", ctype]
        if pre_id != -1:
            arguments.append("--pre-number")
            arguments.append(pre_id)
        ret = subprocess.check_output(arguments, universal_newlines=True)
        return ret.strip()

    def btrfs_delete_snapshot(self, id):
        ret = subprocess.call(["snapper", "delete", id]) 
        return ret == 0
    
    def btrfs_restore_snapshot(self, id):
        ret = subprocess.call(["snapper", "undochange", id+"..0"])
        return ret == 0;
    
    def btrfs_snapshot_diff(self, id):
        ret = subprocess.check_output(["snapper", "status", id+"..0" ], universal_newlines=True);
        return ret

class AptBtrfsSnapper(object):
    """ the high level object that interacts with the snapshot system """

    # normal snapshot
    SNAP_PREFIX = "apt-snapper-"
    SNAPPER_TIME = "%a %d %b %Y %I:%M:%S %p %Z"
    # backname when changing
    BACKUP_PREFIX = SNAP_PREFIX + "old-root-"
    PRE_ID_FILE = "/var/run/apt-btrfs-snapper-pre-id"

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

    def create_btrfs_root_snapshot(self, additional_prefix="", stype="single", sid=-1):  
        snap_id = self._get_now_str()
        name = self.SNAP_PREFIX + additional_prefix + snap_id
        res = self.commands.btrfs_subvolume_snapshot(name, stype, sid)
        print("Created " + stype + " snapshot with snapper as " + name + " with id " + res)
        return res
    
    def create_btrfs_root_snapshot_pre(self, additional_prefix=""):
        id_file = open(self.PRE_ID_FILE, 'r')
        existing = id_file.read() 
        if existing:
            self.delete_snapshot(existing.strip())
            print("Delted orphaned snapshot " + existing.strip())
        
        if os.path.exists(self.PRE_ID_FILE):
            os.remove(self.PRE_ID_FILE)
        id_file = open(self.PRE_ID_FILE, 'w+')
        sid = self.create_btrfs_root_snapshot(additional_prefix, "pre") 
        print("Created tmp file named " +  id_file.name)
        id_file.truncate()
        id_file.write(str(sid).strip())
        id_file.close()
        return sid
    
    def create_btrfs_root_snapshot_post(self, additional_prefix=""):
        try:
            id_file = open(self.PRE_ID_FILE, 'r')
        except FileNotFoundError:
            print("The pre snapshot ID was not found")
            return False
        sid = id_file.read()
        sid = self.create_btrfs_root_snapshot(additional_prefix, "post", sid)
        os.remove(id_file.name)
        return sid
        
    

    def get_btrfs_root_snapshots_list(self, older_than=0, only_id=False):
        """ get the list of available snapshot
            If "older_then" is given (in unixtime format) it will only include
            snapshots that are older then the given date)
        """
        l = []
        if older_than == 0:
            older_than = time.time()
        
        items = self.commands.btrfs_snapshot_list()
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
        print("  \n" + self.commands.btrfs_snapshot_list_pre_post());
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
    
    def show_diff(self, snapshot, post_snapshot):
        id = self.convert_name_to_id(snapshot)
        print("Please wait...\n")
        if id != -1:
            diff = self.commands.btrfs_snapshot_diff(id)
            diff = diff.split("\n")
            for line in diff:
                items = line.split(" ")
                try:
                    bytes_cnt = ""
                    if items[0][0] == "+" or items[0][0] == "c":
                        bytes_cnt = os.path.getsize(items[1])
                        bytes_cnt = self.humansize(bytes_cnt)
                    
                    line = items[0][0] + "  " + bytes_cnt.ljust(10) + " " + items[1]
                   
                except IndexError:
                    pass
                
                print(line)
                
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
            list = self.commands.btrfs_snapshot_list();
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
    
    def humansize(self, nbytes):
        suffixes = ['b', 'kb', 'mb', 'gb', 'tb', 'pb']
        if nbytes == 0: return '0 B'
        i = 0
        while nbytes >= 1024 and i < len(suffixes)-1:
            nbytes /= 1024.
            i += 1
        f = ('%.2f' % nbytes).rstrip('0').rstrip('.')
        return '%s%s' % (f, suffixes[i])

