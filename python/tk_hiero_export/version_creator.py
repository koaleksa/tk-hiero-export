# Copyright (c) 2013 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import os
import shutil
import tempfile

from PySide import QtGui

from hiero.exporters import FnExternalRender
from hiero.exporters import FnTranscodeExporter
from hiero.exporters import FnTranscodeExporterUI

import tank

from .base import ShotgunHieroObjectBase


class ShotgunTranscodeExporterUI(FnTranscodeExporterUI.TranscodeExporterUI):
    """
    Custom Preferences UI for the shotgun transcoder

    Embeds the UI for the std transcoder UI.
    """
    def __init__(self, preset):
        FnTranscodeExporterUI.TranscodeExporterUI.__init__(self, preset)
        self._displayName = "Shotgun Transcode Images"
        self._taskType = ShotgunTranscodeExporter

    def populateUI(self, widget, exportTemplate):
        # create a layout with custom top and bottom widgets
        layout = QtGui.QVBoxLayout(widget)
        top = QtGui.QWidget()
        middle = QtGui.QWidget()
        bottom = QtGui.QWidget()
        layout.addWidget(top)
        layout.addWidget(middle)
        layout.addWidget(bottom)

        # populate the middle with the standard layout
        FnTranscodeExporterUI.TranscodeExporterUI.populateUI(self, middle, exportTemplate)

        layout = QtGui.QVBoxLayout(top)


class ShotgunTranscodeExporter(ShotgunHieroObjectBase, FnTranscodeExporter.TranscodeExporter):
    """
    Create Transcode object and send to Shotgun
    """
    def __init__(self, initDict):
        """ Constructor """
        FnTranscodeExporter.TranscodeExporter.__init__(self, initDict)
        self._resolved_export_path = None
        self._sequence_name = None
        self._shot_name = None
        self._thumbnail = None
        self._quicktime_path = None
        self._temp_quicktime = None

    def buildScript(self):
        """
        Override the default buildScript functionality to also output a temp movie
        file if needed for uploading to Shotgun
        """
        # Build the usual script
        FnTranscodeExporter.TranscodeExporter.buildScript(self)
        if self._preset.properties()['file_type'] == 'mov':
            # already outputting a mov file, use that for upload
            self._quicktime_path = self.resolvedExportPath()
            self._temp_quicktime = False
            return

        self._quicktime_path = os.path.join(tempfile.mkdtemp(), 'preview.mov')
        self._temp_quicktime = True
        nodeName = "Shotgun Screening Room Media"

        framerate = None
        if self._sequence:
            framerate = self._sequence.framerate()
        if self._clip.framerate().isValid():
            framerate = self._clip.framerate()

        preset = FnTranscodeExporter.TranscodePreset("Qt Write", self._preset.properties())
        preset.properties().update({
            'file_type': u'mov',
            'mov': {
                'codec': 'avc1\tH.264',
                'quality': 3,
                'settingsString': 'H.264, High Quality',
                'keyframerate': 1,
            }
        })
        movWriteNode = FnExternalRender.createWriteNode(self._quicktime_path,
            preset, nodeName, framerate=framerate, projectsettings=self._projectSettings)

        self._script.addNode(movWriteNode)

    def taskStep(self):
        """ Run Task """
        if self._resolved_export_path is None:
            self._resolved_export_path = self.resolvedExportPath()
            self._shot_name = self.shotName()
            self._sequence_name = self.sequenceName()

            source = self._item.source()
            self._thumbnail = source.thumbnail(source.posterFrame())

        return FnTranscodeExporter.TranscodeExporter.taskStep(self)

    def finishTask(self):
        """ Finish Task """
        # run base class implementation
        FnTranscodeExporter.TranscodeExporter.finishTask(self)

        sg = self.app.shotgun

        # lookup current login
        sg_current_user = tank.util.get_current_user(self.app.tank)

        # lookup sequence
        sg_sequence = sg.find_one("Sequence",
                                  [["project", "is", self.app.context.project],
                                   ["code", "is", self._sequence_name]])
        sg_shot = None
        if sg_sequence:
            sg_shot = sg.find_one("Shot", [["sg_sequence", "is", sg_sequence], ["code", "is", self._shot_name]])

        # file name
        file_name = os.path.basename(self._resolved_export_path)
        file_name = os.path.splitext(file_name)[0]
        file_name = file_name.capitalize()

        # lookup seq/shot
        data = {
            "user": sg_current_user,
            "created_by": sg_current_user,
            "entity": sg_shot,
            "project": self.app.context.project,
            "sg_path_to_movie": self._resolved_export_path,
            "code": file_name,
        }

        self.app.log_debug("Creating Shotgun Version %s" % str(data))
        vers = sg.create("Version", data)

        if os.path.exists(self._quicktime_path):
            self.app.log_debug("Uploading quicktime to Shotgun... (%s)" % self._quicktime_path)
            sg.upload("Version", vers["id"], self._quicktime_path, "sg_uploaded_movie")
            if self._temp_quicktime:
                shutil.rmtree(os.path.dirname(self._temp_quicktime))


class ShotgunTranscodePreset(ShotgunHieroObjectBase, FnTranscodeExporter.TranscodePreset):
    """ Settings for the shotgun transcode step """
    def __init__(self, name, properties):
        FnTranscodeExporter.TranscodePreset.__init__(self, name, properties)
        self._parentType = ShotgunTranscodeExporter
