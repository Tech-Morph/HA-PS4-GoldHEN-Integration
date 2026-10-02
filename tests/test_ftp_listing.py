import ftplib
import importlib.util
from pathlib import Path
import sys
import unittest

PATH=Path(__file__).resolve().parents[1]/'custom_components/ps4_goldhen/ftp_listing.py'
spec=importlib.util.spec_from_file_location('tested_listing',PATH)
listing=importlib.util.module_from_spec(spec);sys.modules[spec.name]=listing;spec.loader.exec_module(listing)

class FakeFTP:
    def __init__(self,entries=(),error=None,raw=()):self.entries=entries;self.error=error;self.raw=raw;self.list_calls=0;self.cwd_path=None
    def cwd(self,path):self.cwd_path=path
    def mlsd(self):
        if self.error:raise self.error
        yield from self.entries
    def retrlines(self,cmd,callback):
        self.list_calls+=1
        for line in self.raw:callback(line)

class ListingTests(unittest.TestCase):
    def test_real_modify_value_is_utc(self):
        self.assertEqual(listing.parse_modify('20260929065151'),'2026-09-29T06:51:51Z')
    def test_fractional_seconds(self):
        self.assertEqual(listing.parse_modify('20260929065151.25'),'2026-09-29T06:51:51.250000Z')
    def test_invalid_date_returns_unknown(self):
        for v in (None,'','20260230065151','20260929','garbage'):
            self.assertIsNone(listing.parse_modify(v))
    def test_mlsd_skips_pseudo_dirs_and_sorts(self):
        ftp=FakeFTP([('.',{'type':'cdir'}),('..',{'type':'pdir'}),('z.prx',{'type':'file','size':'72240','modify':'20260929065151'}),('data',{'type':'dir'})])
        out=listing.list_directory(ftp,'/')
        self.assertEqual([x['name'] for x in out],['data','z.prx'])
        self.assertEqual(out[1]['modified_utc'],'2026-09-29T06:51:51Z')
        self.assertEqual(out[1]['size'],72240)
        self.assertEqual(out[0]['path'],'/data')
        self.assertEqual(ftp.list_calls,0)
    def test_unsupported_mlsd_falls_back(self):
        ftp=FakeFTP(error=ftplib.error_perm('502 unsupported'),raw=['-rwxrwxrwx 1 0 0 72240 Sep 29 2026 file with spaces.prx'])
        out=listing.list_directory(ftp,'/data/GoldHEN/plugins')
        self.assertEqual(out[0]['name'],'file with spaces.prx')
        self.assertEqual(out[0]['modified'],'Sep 29 2026')
        self.assertIsNone(out[0]['modified_utc'])
        self.assertEqual(out[0]['listing_source'],'list')
    def test_permission_error_not_hidden_by_fallback(self):
        ftp=FakeFTP(error=ftplib.error_perm('550 denied'))
        with self.assertRaises(ftplib.error_perm):listing.list_directory(ftp,'/missing')
        self.assertEqual(ftp.list_calls,0)
    def test_connection_failure_not_hidden(self):
        with self.assertRaises(OSError):listing.list_directory(FakeFTP(error=OSError('offline')),'/')
    def test_unknown_size_and_time(self):
        out=listing.list_directory(FakeFTP([('x',{'type':'file','size':'bad','modify':'bad'})]),'/')
        self.assertIsNone(out[0]['size']);self.assertIsNone(out[0]['modified_utc'])
    def test_invalid_server_names_skipped(self):
        out=listing.list_directory(FakeFTP([('a/b',{'type':'file'}),('bad\r\nname',{'type':'file'})]),'/')
        self.assertEqual(out,[])
    def test_command_injection_path_rejected(self):
        with self.assertRaises(ValueError):listing.list_directory(FakeFTP(),'/data\r\nDELE x')
    def test_empty_directory(self):
        self.assertEqual(listing.list_directory(FakeFTP(),'/'),[])

if __name__=='__main__':unittest.main(verbosity=2)
