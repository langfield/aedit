{-# LANGUAGE OverloadedStrings #-}
{-# LANGUAGE DuplicateRecordFields #-}
module Main (main) where

import Data.Digest.Pure.MD5 (MD5Digest, md5)
import Data.Map (Map)
import Data.Maybe (catMaybes)
import Data.Text (Text)
import Data.Text.ICU.Replace (replaceAll)
import Data.Typeable (Typeable)
import Path ((</>), Abs, Dir, File, Path, toFilePath)
import Path.IO (doesFileExist, ensureDir, listDir, resolveDir', resolveFile')
import Text.Printf (printf)

import qualified Data.Aeson.Micro as JSON
import qualified Data.ByteString.Lazy as LB
import qualified Data.Map as M
import qualified Data.Text as T
import qualified Data.Text.ICU as ICU
-- import qualified Data.ProtocolBuffers as PB
import qualified Database.SQLite.Simple as SQL
import qualified Lib.Git as Git
import qualified Path.Internal


-- ==================== Types, Typeclasses, and Instances ====================


class AbsIO a

-- Extra base types for `Path` to distinguish between paths that exist (i.e.
-- there is a file or directory there) and paths that do not.
data Extant
  deriving Typeable
data Missing
  deriving Typeable

instance AbsIO Extant
instance AbsIO Missing

-- Nid, Mid, Guid, Tags, Flds, SortFld
data SQLNote = SQLNote Integer Integer Text Text Text Text
  deriving Show

data SQLModel = SQLModel
  { sqlModelMid  :: Integer
  , sqlModelName :: Text
  , sqlModelConfigHex :: Text
  }
  deriving Show

data SQLField = SQLField
  { sqlFieldMid  :: Integer
  , sqlFieldOrd  :: Integer
  , sqlFieldName :: Text
  , sqlFieldConfigHex :: Text
  }
  deriving Show

data SQLTemplate = SQLTemplate
  { sqlTemplateMid  :: Integer
  , sqlTemplateOrd  :: Integer
  , sqlTemplateName :: Text
  , sqlTemplateConfigHex :: Text
  }
  deriving Show

newtype Mid = Mid Integer deriving (Ord, Eq)

newtype Nid = Nid Integer deriving (Eq, Ord)
newtype Guid = Guid Text
newtype Tags = Tags [Text]
newtype Fields = Fields (Map FieldName Text)
newtype SortField = SortField Text
newtype ModelName = ModelName Text

type Filename = Text
data MdNote = MdNote Guid ModelName Tags Fields SortField
data ColNote = ColNote MdNote Nid Filename

instance SQL.FromRow SQLNote where
  fromRow = SQLNote <$> SQL.field <*> SQL.field <*> SQL.field <*> SQL.field <*> SQL.field <*> SQL.field

instance SQL.FromRow SQLModel where
  fromRow = SQLModel <$> SQL.field <*> SQL.field <*> SQL.field

instance SQL.FromRow SQLField where
  fromRow = SQLField <$> SQL.field <*> SQL.field <*> SQL.field <*> SQL.field

instance SQL.FromRow SQLTemplate where
  fromRow = SQLTemplate <$> SQL.field <*> SQL.field <*> SQL.field <*> SQL.field

newtype FieldOrd = FieldOrd Integer deriving (Eq, Ord)
newtype FieldName = FieldName Text deriving (Eq, Ord)
newtype TemplateName = TemplateName Text

data Field = Field
  { fieldMid  :: Mid
  , fieldOrd  :: FieldOrd
  , fieldName :: FieldName
  }
data Template = Template
  { templateMid  :: Mid
  , templateOrd  :: FieldOrd
  , templateName :: TemplateName
  }
data Model = Model
  { modelMid  :: Mid
  , modelName :: ModelName
  , modelFieldsAndTemplatesByOrd :: Map FieldOrd (Field, Template)
  }


-- ========================== Path utility functions ==========================


-- Ensure a directory is empty, creating it if necessary, and returning
-- `Nothing` if it was not.
ensureEmpty :: Path Abs Dir -> IO (Maybe (Path Extant Dir))
ensureEmpty dir = do
  ensureDir dir
  contents <- listDir dir
  return $ case contents of
    ([], []) -> Just $ Path.Internal.Path (toFilePath dir)
    _ -> Nothing


-- Ensure a file exists, creating it if necessary.
ensureFile :: Path Abs File -> IO (Path Extant File)
ensureFile file = do
  exists <- doesFileExist file
  case exists of
    True  -> return $ Path.Internal.Path (toFilePath file)
    False -> do
      appendFile (toFilePath file) ""
      return (Path.Internal.Path (toFilePath file))


getExtantFile :: Path Abs File -> IO (Maybe (Path Extant File))
getExtantFile file = do
  exists <- doesFileExist file
  case exists of
    True  -> return $ Just $ Path.Internal.Path (toFilePath file)
    False -> return Nothing


-- Convert from an `Extant` or `Missing` path to an `Abs` path.
absify :: AbsIO a => Path a b -> Path Abs b
absify (Path.Internal.Path s) = Path.Internal.Path s


-- ================================ Core logic ================================


mapModelsByMid :: [SQLModel] -> Map Mid SQLModel
mapModelsByMid = M.fromList . map unpack
  where
    unpack :: SQLModel -> (Mid, SQLModel)
    unpack nt@(SQLModel mid _ _) = (Mid mid, nt)


mapFieldsByMid :: [Field] -> Map Mid (Map FieldOrd Field)
mapFieldsByMid = foldr f M.empty
  where
    g :: FieldOrd -> Field -> Map FieldOrd Field -> Maybe (Map FieldOrd Field)
    g ord fld fieldsByOrd = Just $ M.insert ord fld fieldsByOrd
    f :: Field -> Map Mid (Map FieldOrd Field) -> Map Mid (Map FieldOrd Field)
    f fld@(Field mid ord name) = M.update (g ord fld) mid


mapTemplatesByMid :: [Template] -> Map Mid (Map FieldOrd Template)
mapTemplatesByMid = foldr f M.empty
  where
    g :: FieldOrd -> Template -> Map FieldOrd Template -> Maybe (Map FieldOrd Template)
    g ord tmpl fieldsByOrd = Just $ M.insert ord tmpl fieldsByOrd
    f :: Template -> Map Mid (Map FieldOrd Template) -> Map Mid (Map FieldOrd Template)
    f tmpl@(Template mid ord name) = M.update (g ord tmpl) mid


stripHtmlTags :: String -> String
stripHtmlTags "" = ""
stripHtmlTags ('<' : xs) = stripHtmlTags $ drop 1 $ dropWhile (/= '>') xs
stripHtmlTags (x : xs) = x : stripHtmlTags xs


plainToHtml :: Text -> Text
plainToHtml s = case ICU.find htmlRegex t of
  Nothing  -> T.replace "\n" "<br>" t
  (Just _) -> t
  where
    htmlRegex = "</?\\s*[a-z-][^>]*\\s*>|(\\&(?:[\\w\\d]+|#\\d+|#x[a-f\\d]+);)"
    sub :: Text -> Text
    sub =
      replaceAll "<div>\\s*</div>" ""
        . replaceAll "<i>\\s*</i>" ""
        . replaceAll "<b>\\s*</b>" ""
        . T.replace "&nbsp;" " "
        . T.replace "&amp;" "&"
        . T.replace "&gt;" ">"
        . T.replace "&lt;" "<"
    t = sub s


getModel :: Map Mid (Map FieldOrd (Field, Template)) -> SQLModel -> Maybe Model
getModel fieldsAndTemplatesByMid (SQLModel mid name config) =
  case M.lookup (Mid mid) fieldsAndTemplatesByMid of
    Just m  -> Just (Model (Mid mid) (ModelName name) m)
    Nothing -> Nothing


getFieldsAndTemplatesByMid :: Map Mid (Map FieldOrd Field)
                           -> Map Mid (Map FieldOrd Template)
                           -> Map Mid (Map FieldOrd (Field, Template))
getFieldsAndTemplatesByMid fieldsByMid templatesByMid = M.foldrWithKey f M.empty fieldsByMid
  where
    f :: Mid
      -> Map FieldOrd Field
      -> Map Mid (Map FieldOrd (Field, Template))
      -> Map Mid (Map FieldOrd (Field, Template))
    f mid fieldsByOrd acc = case M.lookup mid templatesByMid of
      Just templatesByOrd ->
        M.insert mid (M.intersectionWith (\fld tmpl -> (fld, tmpl)) fieldsByOrd templatesByOrd) acc
      Nothing -> acc


getField :: SQLField -> Field
getField (SQLField mid ord name _) = Field (Mid mid) (FieldOrd ord) (FieldName name)


getTemplate :: SQLTemplate -> Template
getTemplate (SQLTemplate mid ord name _) = Template (Mid mid) (FieldOrd ord) (TemplateName name)


getFilename :: MdNote -> Text
getFilename (MdNote guid model _ fields (SortField sfld)) =
  (T.pack . stripHtmlTags . T.unpack . plainToHtml) sfld


getFieldTextByFieldName :: [Text] -> Map FieldOrd Field -> Map FieldName Text
getFieldTextByFieldName fs m = M.fromList $ zip (map f (M.toAscList m)) fs
  where
    f :: (FieldOrd, Field) -> FieldName
    f (_, (Field _ _ name)) = name


getColNote :: Map Mid Model -> SQLNote -> Maybe ColNote
getColNote modelsByMid (SQLNote nid mid guid tags flds sfld) =
  ColNote <$> mdNote <*> (Just $ Nid nid) <*> (getFilename <$> mdNote)
  where
    getFieldsByOrd :: Map FieldOrd (Field, Template) -> Map FieldOrd Field
    getFieldsByOrd = M.map fst

    ts = T.words tags
    fs = T.split (== '\x1f') flds
    maybeModel = M.lookup (Mid mid) modelsByMid
    maybeModelName = modelName <$> maybeModel
    maybeFieldsByOrd = (M.map fst . modelFieldsAndTemplatesByOrd) <$> maybeModel
    maybeFieldTextByFieldName = getFieldTextByFieldName fs <$> maybeFieldsByOrd
    mdNote =
      MdNote (Guid guid)
        <$> maybeModelName
        <*> Just (Tags ts)
        <*> (Fields <$> maybeFieldTextByFieldName)
        <*> Just (SortField sfld)


-- Parse the collection and target directory, then call `continueClone`.
clone :: String -> String -> IO ()
clone colPath targetPath = do
  colFile   <- resolveFile' colPath
  targetDir <- resolveDir' targetPath
  maybeColFile <- getExtantFile colFile
  maybeTargetDir <- ensureEmpty targetDir
  case (maybeColFile, maybeTargetDir) of
    (Nothing, _) -> printf "fatal: collection file '%s' does not exist" (show colFile)
    (_, Nothing) -> printf "fatal: targetdir '%s' not empty" (show targetDir)
    (Just colFile, Just targetDir) -> continueClone colFile targetDir


continueClone :: Path Extant File -> Path Extant Dir -> IO ()
continueClone colFile targetDir = do
  -- Hash the collection file.
  colFileContents <- LB.readFile (toFilePath colFile)
  let colFileMD5 = md5 colFileContents
  -- Add the backups directory to the `.gitignore` file.
  writeFile (toFilePath gitIgnore) ".ki/backups"
  -- Create `.ki` and `_media` subdirectories.
  maybeKiDir    <- ensureEmpty (absify targetDir </> Path.Internal.Path ".ki")
  maybeMediaDir <- ensureEmpty (absify targetDir </> Path.Internal.Path "_media")
  case (maybeKiDir, maybeMediaDir) of
    (Nothing, _) -> printf "fatal: new '.ki' directory not empty"
    (_, Nothing) -> printf "fatal: new '_media' directory not empty"
    -- Write repository contents and commit.
    (Just kiDir, Just mediaDir) -> writeInitialCommit colFile targetDir kiDir mediaDir colFileMD5
  where gitIgnore = absify targetDir </> Path.Internal.Path ".gitignore" :: Path Abs File


writeInitialCommit :: Path Extant File
                   -> Path Extant Dir
                   -> Path Extant Dir
                   -> Path Extant Dir
                   -> MD5Digest
                   -> IO ()
writeInitialCommit colFile targetDir kiDir mediaDir colFileMD5 = do
  windowsLinks <- writeRepo colFile targetDir kiDir mediaDir
  Git.runGit gitConfig (Git.initDB False)
  return ()
  where
    gitConfig = Git.makeConfig (toFilePath targetDir) Nothing


writeRepo :: Path Extant File
          -> Path Extant Dir
          -> Path Extant Dir
          -> Path Extant Dir
          -> IO ()
writeRepo colFile targetDir kiDir mediaDir = do
  LB.writeFile (toFilePath $ kiDir </> Path.Internal.Path "config") $ JSON.encode config
  conn  <- SQL.open (toFilePath colFile)
  ns    <- SQL.query_ conn "SELECT (nid,guid,mid,tags,flds,sfld) FROM notes" :: IO [SQLNote]
  nts   <- SQL.query_ conn "SELECT (id,name,config) FROM notetypes" :: IO [SQLModel]
  flds  <- SQL.query_ conn "SELECT (ntid,ord,name,config) FROM fields" :: IO [SQLField]
  tmpls <- SQL.query_ conn "SELECT (ntid,ord,name,config) FROM templates" :: IO [SQLTemplate]
  let fieldsByMid = mapFieldsByMid (map getField flds)
  let templatesByMid = mapTemplatesByMid (map getTemplate tmpls)
  let fieldsAndTemplatesByMid = getFieldsAndTemplatesByMid fieldsByMid templatesByMid
  let models = map (getModel fieldsAndTemplatesByMid) nts
  let modelsByMid = M.fromList (catMaybes $ map (fmap (\m -> (modelMid m, m))) models)
  let colnotesByNid = M.fromList $ catMaybes $ map (fmap unpack . getColNote modelsByMid) ns
  writeDecks targetDir colnotesByNid
  where
    remote = JSON.Object $ M.singleton "path" $ (JSON.String . T.pack . toFilePath) colFile
    config = JSON.Object $ M.singleton "remote" $ remote

    unpack :: ColNote -> (Nid, ColNote)
    unpack c@(ColNote _ nid _) = (nid, c)


writeDecks :: Path Extant Dir -> Map Nid ColNote -> IO ()
writeDecks targetDir colnotesByNid = do
  return ()


initMedia :: Path Extant Dir -> IO LgRepo
initMedia remoteMediaDir = do
  repo <- openLgRepository $ defaultRepositoryOptions { repoPath = toFilePath remoteMediaDir }


main :: IO ()
main = print "Hello"
