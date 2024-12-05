import logging
import os
import pwd
import re
import time
from datetime import datetime
from pathlib import Path
from shutil import rmtree
from typing import Optional, Tuple

import pandas as pd

from subscript.genertobs_unstable._datatypes import ObservationType
from subscript.genertobs_unstable._utilities import check_and_fix_str, inactivate_rows

GENDATA_RFT_EXPLAINER = """-------------------------
-- GENDATA_RFT  -- Create files with simulated rft pressure
-------------------------
-- ERT doc: https://fmu-docs.equinor.com/docs/ert/reference/forward_models.html#GENDATA_RFT

"""

GENDATA_EXPLAINER = """-------------------------
-- GEN_DATA  -- Create GEN_DATA of rft for usage in AHM
-------------------------
-- ERT doc: https://fmu-docs.equinor.com/docs/ert/reference/configuration/keywords.html#gen-data

--       ert id       Result file name           input format         report step
"""


def add_time_stamp(string="", record_type="f", comment_mark="--"):
    """Add commented line with user and timestamp

    Args:
        string (str): the string to stamp
        record_type (str, optional): specifies if it is file or folder. Defaults to "f".

    Returns:
        _type_: _description_
    """
    ctime = datetime.now().strftime("%Y-%m-%d:%H:%M:%S")
    user = pwd.getpwuid(os.getuid())[0]
    type_str = "file" if record_type == "f" else "folder"

    time_stamped = (
        f"{comment_mark}This {type_str} is autogenerated by {user} "
        f"running genertobs_unstable at {ctime}\n"
    )

    time_stamped += f"{comment_mark} DO NOT EDIT THIS {type_str.upper()} MANUALLY!\n"

    time_stamped += string
    return time_stamped


def write_csv_with_comment(file_path, frame):
    """Write to csv file with timestamped header

    Args:
        file_path (str): path to file
        frame (pd.DataFrame): the dataframe to write
    """

    with open(file_path, "w", encoding="utf-8") as stream:
        # stream.write(add_time_stamp(comment_mark="#"))
        frame.to_csv(stream, index=False, header=False, sep=" ")


def write_timeseries_ertobs(obs_dict: dict):
    """Make ertobs string to from dictionary

    Args:
        obs_dict (dict): the dictionary to extract from

    Returns:
        str: string to write into ertobs file
    """
    logger = logging.getLogger(__name__ + ".write_timeseries_ertobs")
    logger.debug("%s observations to write", obs_dict)
    obs_frames = []
    for element in obs_dict:
        logger.debug("Element to extract from %s", element)
        key = element["vector"]
        logger.debug(key)
        obs_frame = inactivate_rows(element["data"])
        obs_frame["class"] = "SUMMARY_OBSERVATION"
        obs_frame["key"] = f"KEY={key}" + ";};"
        order = ["class", "label", "value", "error", "date", "key"]
        obs_frame = obs_frame[order]
        obs_frame["value"] = "{VALUE=" + obs_frame["value"].astype(str) + ";"
        obs_frame["error"] = "ERROR=" + obs_frame["error"].astype(str) + ";"
        obs_frame["date"] = "DATE=" + obs_frame["date"].astype(str) + ";"
        obs_frames.append(obs_frame)
    obs_frames_str = pd.concat(obs_frames).to_string(header=False, index=False)
    obs_str = re.sub(r" +", " ", obs_frames_str) + "\n"  # type: ignore
    logger.debug("Returning %s", obs_str)
    return obs_str


def select_from_dict(keys: list, full_dict: dict):
    """Select some keys from a bigger dictionary

    Args:
        keys (list): the keys to select
        full_dict (dict): the dictionary to extract from

    Returns:
        dict: the subselection of dict
    """
    return {key: full_dict[key] for key in keys}


def create_rft_ertobs_str(element: pd.Series, prefix: str, obs_file: Path) -> str:
    """Create the rft ertobs string for specific well

    Args:
        element (RftConfigElement): element with data
        prefix (str): prefix to be included
        obs_file (str): name file with corresponding well observations

    Returns:
        str: the string
    """
    return (
        f"GENERAL_OBSERVATION {element['well_name']}_{prefix}_OBS "
        + "{"
        + f"DATA={element['well_name']}_{prefix}_SIM;"
        + f" RESTART = {element['restart']}; "
        + f"OBS_FILE = {obs_file}"
        + ";};\n"
    )


def create_rft_gendata_str(element: pd.Series, prefix, outfolder_name: str) -> str:
    """Create the string to write as gendata call

    Args:
        element (pd.Series): data row
        prefix (str): prefix to be included
        outfolder_name (str): path to folder where results are stored

    Returns:
        str: the string
    """
    separator_string = "_" if prefix == "PRESSURE" else f"_{prefix}_"
    return (
        f"GEN_DATA {element['well_name']}_{prefix}_SIM "
        + f"RESULT_FILE:{outfolder_name}/RFT{separator_string}{element['well_name']}_%d"
        + f" REPORT_STEPS:{element['restart']}\n"
    )


def write_genrft_str(
    parent: Path, well_date_path: Path, layer_zone_table: Path, outfolder_name: str
) -> str:
    """write the string to define the GENDATA_RFT call

    Args:
        parent (str): path where rfts are stored
        well_date_path (str): path to file with well, date, and restart number
        layer_zone_table (str): path to zones vs layer file
        outfolder_name (str): path to where results will be restored

    Returns:
        str: the string
    """
    logger = logging.getLogger(__name__ + ".write_genrft_str")
    string_warning = (
        "\n\n!!Remember that the zone layer file: %s will need to have path relative\n"
        + " to runpath for realization, so please double check that this is the case,\n"
        + " otherwise you will just stop ert later!!\n\n"
    )
    time.sleep(2)
    logger.warning(
        string_warning,
        layer_zone_table,
    )
    str_parent = str(parent)
    string = (
        GENDATA_RFT_EXPLAINER
        + f"DEFINE <RFT_INPUT> {parent}\n"
        + f"FORWARD_MODEL MAKE_DIRECTORY(<DIRECTORY>={outfolder_name})\n"
        + "FORWARD_MODEL GENDATA_RFT(<PATH_TO_TRAJECTORY_FILES>=<RFT_INPUT>,"
        + "<WELL_AND_TIME_FILE>=<RFT_INPUT>/"
        + f"{str(well_date_path).replace(str_parent, '')},"
        + f"<ZONEMAP>={str(layer_zone_table)},"
        + f" <OUTPUTDIRECTORY>={outfolder_name})\n\n"
    )
    logger.debug("Returning %s", string)
    return string


def write_rft_ertobs(
    rft_dict: dict, well_date_file: Path, parent_folder: Path
) -> Tuple[str, str]:
    """Write all rft files for rft dictionary, pluss info str

    Args:
        rft_dict (dict): the rft information
        parent_folder (str, optional): path to parent folder. Defaults to "".

    Returns:
        str: ertobs strings for rfts
    """
    logger = logging.getLogger(__name__ + ".write_rft_ertobs")
    rft_folder = Path(parent_folder) / "rft"
    rft_folder.mkdir(exist_ok=True)
    logger.debug("%s observations to write", rft_dict)
    well_date_list = []
    rft_ertobs_str = ""
    gen_data = ""
    prefix = rft_dict["config"].metadata.subtype.name
    outfolder_name = "gendata_rft"
    logger.debug("prefix is %s", prefix)
    for element in rft_dict["data"]:
        logger.debug(element["well_name"])
        obs_file = write_well_rft_files(rft_folder, prefix, element)
        if obs_file is not None:
            well_date_list.append(
                [element["well_name"], element["date"], element["restart"]]
            )
            rft_ertobs_str += create_rft_ertobs_str(element, prefix, obs_file)
            gen_data += create_rft_gendata_str(element, prefix, outfolder_name)
            logger.debug(
                "\n---------------Before \n%s--------------------\n\n", gen_data
            )

    well_date_frame = pd.DataFrame(
        well_date_list, columns=["well_name", "date", "restart"]
    )

    write_csv_with_comment(well_date_file, well_date_frame)
    logger.debug("Written %s", str(well_date_file))
    logger.debug("\n---------------After \n%s--------------------\n\n", gen_data)

    return rft_ertobs_str, gen_data


def write_well_rft_files(
    parent_folder: Path, prefix: str, element: dict
) -> Optional[Path]:
    """Write rft files for rft element for one well

    Args:
        parent_folder (str): parent to write all files to
        prefix (str): prefix defining if it is pressure or saturation
        element (dict): the info about the element

    Returns:
        str: ertobs string for well
    """
    logger = logging.getLogger(__name__ + ".write_well_rft_files")
    well_frame = inactivate_rows(element["data"])
    if well_frame.empty:
        return None
    fixed_file_name = check_and_fix_str(element["well_name"])
    obs_file = (parent_folder / f"{prefix.lower()}_{fixed_file_name}.obs").resolve()
    position_file = parent_folder / f"{fixed_file_name}.txt"
    logger.debug("Writing %s and %s", obs_file, position_file)
    obs_frame = well_frame[["value", "error"]]
    logger.debug("observations\n%s", obs_frame)
    write_csv_with_comment(obs_file, obs_frame)
    position_frame = well_frame[["x", "y", "md", "tvd", "zone"]]
    logger.debug("positions for\n%s", position_frame)
    write_csv_with_comment(position_file, position_frame)

    return obs_file


def write_dict_to_ertobs(obs_list: list, parent: Path) -> str:
    """Write all observation data for ert

    Args:
        obs_list (list): the list of all observations
        parent (str, optional): location to write to. Defaults to "".

    Returns:
        str: parent folder for all written info
    """
    logger = logging.getLogger(__name__ + ".write_dict_to_ertobs")
    logger.debug("%s observations to write", len(obs_list))
    logger.debug(obs_list)

    if parent.exists():
        logger.warning("%s exists, deleting and overwriting contents", str(parent))
        rmtree(parent)
    parent.mkdir()
    well_date_file_name = parent / "rft/well_date_restart.txt"
    gendata_rft_folder_name = "gendata_rft"
    gendata_rft_str = ""
    obs_str = add_time_stamp()
    gen_data = ""
    readme_file = parent / "readme.txt"
    readme_file.write_text(add_time_stamp(record_type="d"))
    for obs in obs_list:
        logger.debug(obs)
        obs_str += f"--\n--{obs['config'].name}\n"
        if obs["config"].type == ObservationType.SUMMARY:
            obs_str += write_timeseries_ertobs(obs["data"])

        elif obs["config"].type == ObservationType.RFT:
            if gendata_rft_str == "":
                gendata_rft_str = write_genrft_str(
                    parent / "rft",
                    well_date_file_name,
                    obs["config"].plugin_arguments.zonemap,
                    gendata_rft_folder_name,
                )
            rft_str_element, gen_data_element = write_rft_ertobs(
                obs, well_date_file_name, parent
            )
            obs_str += rft_str_element
            gen_data += gen_data_element
            logger.debug("No gen_data is %s characters (%s)", len(gen_data), gen_data)
        else:
            logger.warning(
                "Currently not supporting other formats than timeseries and rft"
            )
    ertobs_file = parent / "ert_observations.obs"
    ertobs_file.write_text(obs_str)
    if gen_data:
        gen_data = gendata_rft_str + GENDATA_EXPLAINER + gen_data
        gen_data_file = parent / "gen_data_rft_wells.ert"
        gen_data_file.write_text(add_time_stamp(gen_data))
        logger.debug("Written %s", str(gen_data_file))

    # Set to read only for others, user needs all rights for tests
    # group is able to delete
    parent.chmod(0o774)
    return obs_str