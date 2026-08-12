import os
import re
from collections import defaultdict
from .config import Config
from os.path import commonprefix


def input_validation(name):
    """Checks if the experiment ID contains illegal characters."""
    if not name:
        return False
    # Avoid characters that break shell commands or file paths
    for char in name:
        if char in [r"?", "\\", r"/", r".", r",", r":", r";", r" "]:
            return False
    return True

def convert_realpaths_to_wildcards(paths):
    """
    Convert a list of file paths into a single wildcard pattern.
    If only one file, return it directly.
    """
    if len(paths) == 1:
        return paths[0]

    dirs = [os.path.dirname(p) for p in paths]
    basenames = [os.path.basename(p) for p in paths]

    if len(set(dirs)) > 1:
        # fallback: cannot wildcard across directories, join with comma
        return ",".join(paths)

    dir_prefix = dirs[0]
    common_prefix = os.path.commonprefix(basenames)
    reversed_basenames = [b[::-1] for b in basenames]
    common_suffix_reversed = os.path.commonprefix(reversed_basenames)
    common_suffix = common_suffix_reversed[::-1]

    wildcard = common_prefix + "*" + common_suffix
    return os.path.join(dir_prefix, wildcard)

def detect_samples_files(folder=None):
    """
    Detects fastq files up to 2 levels deep. 
    Uses folder context for 'barcode*' directories and 
    common prefix grouping for others.
    """
    target = folder or Config.IMPORT_FOLDER
    if not os.path.exists(target):
        return {}

    root_base = os.path.abspath(target)
    base_level = root_base.count(os.sep)
    fastq_pattern = re.compile(r'\.f(ast)?q(\.gz)?$', re.IGNORECASE)
    
    chunk_suffix_pattern = re.compile(r'([._-](part\d+|\d+|[Rr][12]))$', re.IGNORECASE)
    
    samples_map = defaultdict(list)

    for root, dirs, files in os.walk(root_base):
        current_depth = root.count(os.sep) - base_level
        if current_depth >= 2:
            dirs[:] = []

        current_fastq = [f for f in files if fastq_pattern.search(f)]
        if not current_fastq:
            continue

        folder_name = os.path.basename(root)

        if folder_name.lower().startswith("barcode"):
            names_only = [fastq_pattern.sub('', f) for f in current_fastq]
            prefix = commonprefix(names_only)
            sample_name = re.sub(r'[._-]+$', '', prefix)
            
            if len(sample_name) < 2:
                sample_name = folder_name
                
            for f in current_fastq:
                samples_map[sample_name].append(os.path.join(root, f))
        
        else:
            for f in current_fastq:
                basename = fastq_pattern.sub('', f)
                sample_identity = chunk_suffix_pattern.sub('', basename)
                sample_name = re.sub(r'[._-]+$', '', sample_identity)
                samples_map[sample_name].append(os.path.join(root, f))

    final_files = {}
    for sample, paths in samples_map.items():
        paths.sort()
        final_files[sample] = convert_realpaths_to_wildcards(paths)
        
    return final_files
