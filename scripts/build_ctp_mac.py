"""Build the pinned vnpy_ctp against its bundled macOS SDK in an isolated copy."""
from pathlib import Path
import subprocess
import shutil
import sys
import json
import hashlib
import difflib

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'raw/repos/vnpy_ctp_mac_6_7_7'
DST = ROOT / 'build/vnpy_ctp_mac_6_7_7'
EXPECTED = 'fa199f70dac9e242c20e925c17e2241b877e694f'
if sys.platform != 'darwin':
    raise SystemExit('This compatibility build is for macOS only.')
manifest=json.loads((ROOT/'reports/ctp-compat-source.json').read_text())
assert manifest['commit']==EXPECTED
for entry in manifest['git_tree']:
    path=SRC/entry['path']
    data=str(path.readlink()).encode() if path.is_symlink() else path.read_bytes()
    assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==entry['sha'],path
if DST.exists():
    raise SystemExit('Build copy already exists; inspect/reuse it rather than overwrite changes.')
shutil.copytree(SRC, DST, ignore=shutil.ignore_patterns('.git'))
patches=[]
for module, api in [('vnctpmd', 'Md'), ('vnctptd', 'Trader')]:
    p = DST / f'vnpy_ctp/api/vnctp/{module}/{module}.cpp'
    before = p.read_text(encoding='gb18030')
    after = before
    # Shutdown joins a thread that needs the GIL; release it around that call.
    cls = 'MdApi' if api == 'Md' else 'TdApi'
    after = after.replace(f'.def("exit", &{cls}::exit)', f'.def("exit", &{cls}::exit, pybind11::call_guard<pybind11::gil_scoped_release>())')
    p.write_text(after, encoding='gb18030')
    patches.extend(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile=f'a/{p.relative_to(DST)}', tofile=f'b/{p.relative_to(DST)}'))
setup = '''from setuptools import setup, Extension, find_packages
import pybind11
from pathlib import Path
root = Path(__file__).resolve().parent
api = root / 'vnpy_ctp/api'
exts = []
for module, framework in [('vnctpmd','thostmduserapi_se'),('vnctptd','thosttraderapi_se')]:
    exts.append(Extension('vnpy_ctp.api.'+module,
        sources=[str(api/'vnctp'/module/(module+'.cpp'))],
        include_dirs=[pybind11.get_include(),str(api/'include/mac'),str(api/'vnctp')],
        extra_compile_args=['-std=c++17','-O1'],
        extra_link_args=['-F'+str(api),'-framework',framework,'-Wl,-rpath,'+str(api)],
        language='c++'))
setup(name='vnpy_ctp',version='6.7.7.2',packages=find_packages(),ext_modules=exts,
      install_requires=['vnpy>=3.0.0'])
'''
(DST/'setup_mac.py').write_text(setup)
(ROOT/'reports/ctp-mac-compat.patch').write_text(''.join(patches))
subprocess.run([sys.executable, 'setup_mac.py', 'build_ext', '--inplace'], cwd=DST, check=True)
# Install a wheel without invoking upstream's incompatible Meson link configuration.
subprocess.run([sys.executable,'setup_mac.py','bdist_wheel'],cwd=DST,check=True)
wheel = next((DST/'dist').glob('*.whl'))
subprocess.run(['uv','pip','install','--python',str(ROOT/'.venv/bin/python'),'--no-deps',str(wheel)],check=True)
print('Built and installed:',wheel)
print('Framework runtime path remains in',DST,'; do not move/delete this build copy.')
