import configparser
from pathlib import Path
from src.data import *
from src.sorting import TAGS_NAMES
from src.common import *
from src.patches import PatchSchema

DEFAULT_CONFIG = {
    'database': {
        'auto_load': True,
        'auto_save': True
    },
    'synth_interface': {
        'quick_export_as': FXP_CHUNK,
        'export_to': Path.home()
    }
}
TMP_FXP_NAME = '%s_tmp.%s' % (APP_NAME_INLINE, FXP_FILE_EXT)

STATUS_MSGS = {
    STATUS_READY: 'Ready.',
    STATUS_IMPORT: 'Importing banks...',
    STATUS_NAME_TAG: 'Running name-based tagging...',
    STATUS_SIM_TAG: 'Running parameter-based tagging...',
    STATUS_OPEN: 'Opening database...',
    STATUS_SEARCH: 'Searching...',
    STATUS_WAIT: 'Working...'
}


def searcher(func):
    """Wrapper for functions that perform searches."""

    def inner(self, q):
        if len(q) > 0 and self.last_query != q:
            self.status(STATUS_SEARCH)
            self.last_query = q
            func(self, q)
            self.search_done()
            self.unwait()
            return True
        return False

    return inner


def reloads(func):
    """Wrapper for functions that require a reload of the view."""

    def inner(self, *args, **kwargs):
        ret = func(self, *args, **kwargs)
        self.refresh()
        return ret

    return inner


class App:
    """Implements the program's controller."""

    __db: PatchDatabase  # The active patch database
    __config: configparser.ConfigParser
    __data_dir: Path
    __config_file: Path
    schema: PatchSchema

    quick_tmp: Path  # Temporary file for quick export
    active_patch: int = -1  # Index in db of currently active patch
    last_query = ''  # Last search query, to avoid redundant queries

    tags = []  # tag indexes for active database
    banks = []  # bank indexes for active database

    def __init__(self, schema: PatchSchema):
        """Creates a new instance of the program."""

        self.status(STATUS_OPEN)

        self.__data_dir = Path.home() / ('.%s' % APP_NAME_INLINE)
        self.__config_file = self.__data_dir / 'config.ini'
        self.schema = schema
        self.__db = PatchDatabase(self.schema)
        self.__config = configparser.ConfigParser()

        self.load_config()
        self.status(STATUS_READY)

    def info(self, msg: str):
        """Define this. It should display an informational message to the user."""
        ...

    def err(self, msg: str):
        """Define this. It should display an error message to the user."""
        ...

    def put_patch(self, patch):
        """Define this. It should add the `patch` to a list of patches visible to the user."""
        ...

    def wait(self):
        """Define this. It should inform the user that the program is busy."""
        ...

    def unwait(self):
        """Define this. It should inform the user that the program is no longer busy."""
        ...

    def empty_patches(self):
        """Define this. It should empty the user-facing list of patches."""
        ...

    def search_done(self):
        """Define this. It's called whenever a search is finished."""
        ...

    def update_meta(self) -> list:
        """This should update the user-facing metadata list with the return value of the super function."""

        if self.active_patch > -1:
            return [
                'fix', 'me'
            ]
        else:
            return []

    @searcher
    def search_by_tags(self, tags: list):
        """Searches for patches matching `tags`."""

        self.__db.find_patches_by_tags(tags).apply(self.put_patch, axis=1)

    @searcher
    def search_by_bank(self, bank: str):
        """Searches for patches in bank `bank`."""

        self.__db.find_patches_by_val(
            bank, 'bank', exact=True).apply(self.put_patch, axis=1)

    @searcher
    def keyword_search(self, kwd: str):
        """Searches for patches matching keyword `kwd`."""

        self.__db.keyword_search(kwd).apply(self.put_patch, axis=1)

    def refresh(self):
        """Refreshes cached indexes."""

        self.tags = self.__db.tags
        self.banks = self.__db.banks
        self.status(STATUS_READY)

    @reloads
    def tag_names(self):
        """Tags patches based on their names."""

        self.status(STATUS_NAME_TAG)
        self.__db.tags_from_val_defs(TAGS_NAMES, 'patch_name')

    @reloads
    def tag_similar(self):
        """Tags patches based on their similarity to other patches."""

        self.status(STATUS_WAIT)
        acc = self.__db.train_classifier()
        self.info('Based on your current tags, this tagging method is estimated to be %f%% accurate. ' % (acc * 100) +
                  'To improve its accuracy, manually tag some untagged patches and correct existing tags, then run '
                  'this again.')
        self.status(STATUS_SIM_TAG)
        self.__db.classify_tags()

    def status(self, msg):
        """Fully implement this function by updating a user-facing status indicator before calling the super."""

        if msg == STATUS_READY:
            self.unwait()
        else:
            self.empty_patches()
            self.last_query = ''
            self.wait()

    @reloads
    def new_database(self, patches_dir):
        """Creates a new database with patches from `dir`."""

        self.status(STATUS_IMPORT)
        self.__db.bootstrap(Path(patches_dir))

    @reloads
    def open_database(self, path, silent=False):
        """Loads a previously saved database."""

        if not isinstance(path, Path):
            path = Path(path)

        if path.is_dir():
            try:
                self.__db.from_disk(path)
            except:
                if not silent:
                    raise Exception('That is not a valid data folder.')

    def save_database(self, path):
        """Saves the active database to disk."""

        if self.__db.is_active():
            self.__db.to_disk(path)

    def load_config(self):
        """Loads the config file for the program, or create one if it doesn't exist."""

        self.__data_dir.mkdir(exist_ok=True)
        self.__config.read_dict(DEFAULT_CONFIG)
        if self.__config_file.is_file():
            self.__config.read(self.__config_file)
        else:
            self.__config_file.touch()

        if self.__config.get('synth_interface', 'quick_export_as') == PATCH_FILE:
            self.quick_tmp = Path(
                self.__data_dir / ('%s.%s' % (self.schema.file_base, self.schema.file_ext))).resolve()
        else:
            self.quick_tmp = Path(self.__data_dir / TMP_FXP_NAME).resolve()
        self.quick_tmp.touch(exist_ok=True)

        if self.__config.getboolean('database', 'auto_load'):
            self.open_database(self.__data_dir, silent=True)

    def export_patch(self, ind: int, typ=PATCH_FILE, path=None):
        """Exports the patch at index `ind`."""

        if ind:
            if path is None:
                path = Path(self.__config.get(
                    'synth_interface', 'export_to'))

            self.__db.write_patch(ind, typ, path)

    def quick_export(self, ind: int):
        """Exports the patch at index `ind` using quick settings. The patch will be saved at the path
        `self.quick_tmp`. """

        self.__db.write_patch(ind, self.__config.get('synth_interface', 'quick_export_as'), self.quick_tmp)

    def end(self):
        """Housekeeping before exiting the program."""

        if self.__config.getboolean('database', 'auto_save'):
            self.save_database(self.__data_dir)

        with open(self.__config_file, 'w') as cfile:
            self.__config.write(cfile)
        self.quick_tmp.unlink(missing_ok=True)


__all__ = ['App', 'STATUS_MSGS']
