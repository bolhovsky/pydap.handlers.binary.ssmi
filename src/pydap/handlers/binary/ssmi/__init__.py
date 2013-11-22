"""A Pydap handler for binary SSMI files."""

import os
import re

import gzip

from pkg_resources import get_distribution
from pydap.model import *
from pydap.handlers.lib import BaseHandler
from pydap.handlers.helper import constrain
from pydap.lib import parse_qs, walk
from pydap.exceptions import OpenFileError
import numpy as np
import struct
import copy

class BinarySsmiHandler(BaseHandler):

    # __version__ = get_distribution("pydap.handlers.binary.ssmi").version
    extensions = re.compile(r".*f[0-9]{2}_[0-9]{8}[0-9a-z]{2}(\.gz)?$", re.IGNORECASE)

    def __init__(self, filepath):
        BaseHandler.__init__(self)
        self.filepath = filepath
        self.filename = os.path.split(filepath)[1]
        self.dataset = DatasetType(name=self.filename, attributes={
            "SSMI_GLOBAL" : {
                "CONVENTIONS" : "COARDS",
                "short_name" : "SSMIS",
                "long_name" : "Special Sensor Microwave Image Sounder",
                "producer_agency" : "Remote Sensing Systems",
                "product_version" : "Version-7",
                "spatial_resolution" : "0.25 degree",
                "temporal_resolution" : "Daily",
                "instrument" : "SSMIS",
                "original_filename" : self.filename,
            }
        })

        _dim = ('lon', 'lat', 'part_of_day')
        _shape = (1440, 720, 2)
        _type = UInt16

        self.variables = [
            BaseType(
                name='time',
                data=None,
                shape=_shape,
                dimensions=_dim,
                type=_type,
                attributes={
                    'long_name' : 'Time',
                    'add_offset' : 0,
                    'scale_factor' : 6,
                    '_FillValue' : 254,
                    'units' : 'minutes',
                    'coordinates': 'lon lat'
                }
            ),
            BaseType(
                name='wspd',
                data=None,
                shape=_shape,
                dimensions=_dim,
                type=_type,
                attributes={
                    'long_name' : '10 meter Surface Wind Speed',
                    'add_offset' : 0,
                    'scale_factor' : 0.2,
                    '_FillValue' : 254,
                    'units' : 'm/sec',
                    'coordinates': 'lon lat'
                }
            ),
            BaseType(
                name='vapor',
                data=None,
                shape=_shape,
                dimensions=_dim,
                type=_type,
                attributes=({
                    'long_name' : 'Atmospheric Water Vapor',
                    'add_offset' : 0,
                    'scale_factor' : 0.3,
                    '_FillValue' : 254,
                    'units' : 'mm',
                    'coordinates': 'lon lat'
                })
            ),
            BaseType(
                name='cloud',
                data=None,
                shape=_shape,
                dimensions=_dim,
                type=_type,
                attributes=({
                    'long_name' : 'Cloud liquid Water',
                    'add_offset' : -0.05,
                    'scale_factor' : 0.01,
                    '_FillValue' : 254,
                    'units' : 'mm',
                    'coordinates': 'lon lat'
                })
            ),

            BaseType(
                name='rain',
                data=None,
                shape=_shape,
                dimensions=_dim,
                type=_type,
                attributes=({
                    'long_name' : 'Rain Rate',
                    'add_offset' : 0,
                    'scale_factor' : 0.1,
                    '_FillValue' : 254,
                    'units' : 'mm/hr',
                    'coordinates': 'lon lat'
                })
            )]

        lonVar = BaseType(
            name='lon',
            data=None,
            shape=(1440,),
            dimensions=('lon',),
            type=Float32,
            attributes=({
                'long_name' : 'longitude',
                # 'add_offset' : 0,
                # 'scale_factor' : 1,
                'valid_range' : '-180, 180',
                'units' : 'degrees_east'
            })
        )

        latVar = BaseType(
            name='lat',
            data=None,
            shape=(720,),
            dimensions=('lat',),
            type=Float32,
            attributes=({
                'long_name' : 'latitude',
                # 'add_offset' : 0,
                # 'scale_factor' : 1,
                'valid_range' : '-90, 90',
                'units' : 'degrees_north'
            })
        )

        partVar = BaseType(
            name='part_of_day',
            data=None,
            shape=(2,),
            dimensions=('part_of_day',),
            type=UInt16,
            attributes=({
                'long_name' : 'part_of_day',
                # 'add_offset' : 0,
                # 'scale_factor' : 1,
                'valid_range' : '0, 1',
                'units' : 'part_of_day'
            })
        )

        self.dataset['lon'] = lonVar
        self.dataset['lat'] = latVar
        self.dataset['part_of_day'] = partVar

        for variable in self.variables:
            # print variable.name
            g = GridType(name=variable.name)
            g[variable.name] = variable

            g['lon'] = lonVar.__deepcopy__()
            g['lat'] = latVar.__deepcopy__()
            g['part_of_day'] = partVar.__deepcopy__()
            g.attributes = variable.attributes

            self.dataset[variable.name] = g
            # self.dataset[variable.name].attributes = variable.attributes


    def parse_constraints(self, environ):
        projection, selection = parse_qs(environ.get('QUERY_STRING', ''))
        if projection:
            try:
                if self.filepath.endswith('gz'):
                    file = gzip.open(self.filepath, 'rb')
                else:
                    file = open(self.filepath, "rb")
                bytes_read = np.frombuffer(file.read(), np.uint8)
                file.close()
            except Exception, exc:
                message = 'Unable to open file %s: %s' % (self.filepath, exc)
                raise OpenFileError(message)

            for var in projection:
                var_name = var[len(var)-1][0]

                if var_name in ['lat', 'lon', 'part_of_day']:
                    if var_name == 'lon':
                        self.dataset['lon'].data = self.read_variable_lon()
                    elif var_name == 'lat':
                        self.dataset['lat'].data = self.read_variable_lat()
                    elif var_name == 'part_of_day':
                        self.dataset['part_of_day'].data = self.read_variable_part()
                else:
                    for variable in self.variables:
                        if variable.name == var_name:
                            slices = var[len(var)-1][1]
                            if len(slices) != 3:
                                raise ValueError('Cannot obtain slices for %s. '
                                                 'Should be 3 slices, but %d found' % (var_name, len(slices)))
                            print 'retrieving %s' % var_name, slices
                            index = 0
                            for i in range(len(self.variables)):
                                if self.variables[i].name == variable.name:
                                    index = i

                            self.dataset[variable.name]['lon'].data = self.read_variable_lon(slices[0])
                            self.dataset[variable.name]['lat'].data = self.read_variable_lat(slices[1])
                            self.dataset[variable.name]['part_of_day'].data = self.read_variable_part(slices[2])

                            self.dataset[variable.name][variable.name].data = self.read_variable_data(bytes_read, index, slices)

        dataset_copy = copy.deepcopy(self.dataset)
        if projection:
            # val_arr = ['lat', 'lon', 'part_of_day']
            val_arr = []
            for proj in projection:
                val_arr.append(proj[0][0])

            for key in dataset_copy.keys():
                if not key in val_arr:
                    dataset_copy.pop(key, None)
        return dataset_copy

    def read_variable_lat(self, slices_lat):
        latMax = 719
        buf = np.empty(len(range(latMax+1)[slices_lat]), np.float32)
        cnt = 0

        for j in range(720)[slices_lat]:
            latValue = 0.25 * j - 90.125
            buf[cnt] = latValue
            cnt += 1

        return buf

    def read_variable_lon(self, slices_lot):
        lonMax = 1439

        buf = np.empty(len(range(lonMax+1)[slices_lot]), np.float32)
        cnt = 0
        for i in range(1440)[slices_lot]:
            lonValue = 0.25 * (i+1) - 0.125
            buf[cnt] = lonValue
            cnt += 1

        return buf

    def read_variable_part(self, slices_part):
        buf = np.empty(len(range(2)[slices_part]), np.uint16)
        cnt = 0
        for i in range(2)[slices_part]:
            buf[cnt] = i
            cnt += 1
        return buf

    def read_variable_data(self, bytes, index, slices):
        buf = np.empty((len(range(1440)[slices[0]]), len(range(720)[slices[1]]), len(range(2)[slices[2]])), np.uint16)

        for i in range(1440)[slices[0]]:
            for j in range(720)[slices[1]]:
                for k in range(2)[slices[2]]:
                    byteIndex = (1440 * j + i) + (1440 * 720 * index) + (1440 * 720 * 5 * k)
                    buf[i-slices[0].start][j-slices[1].start][k-slices[2].start] = bytes[byteIndex]

        return buf

def _test():

    test_values = {}
    test_values['wspd'] = [253.00, 253.00, 6.40, 5.80, 5.60]
    test_values['vapor'] = [253.00, 253.00, 60.60, 60.90, 60.30]
    test_values['cloud'] = [253.00, 253.00, 0.07, 0.08, 0.06]
    test_values['rain'] = [253.00, 253.00, 0.00, 0.00, 0.00]

    values = ['wspd', 'vapor', 'cloud', 'rain']

    application = BinarySsmiHandler("../../../../../test/f10_19950120v7.gz")
    environ = {}

    for value in values:
        environ['QUERY_STRING'] = value+"[171:1:171][273:1:277][0]"
        dd = application.parse_constraints(environ)

        scale_factor = dd[value].attributes['scale_factor']
        add_offset = dd[value].attributes['add_offset']

        _value_arr = dd[value][value][:]
        _shape = _value_arr.shape

        for j in range(_shape[1]):
            for i in range(_shape[0]):
                for k in range(_shape[2]):
                    if _value_arr[i][j][k]> 250:
                        if _value_arr[i][j][k] != test_values[value][j]:
                            print value, ": failed"
                            return 1
                    else:
                        if round((_value_arr[i][j][k]*scale_factor + add_offset)*1000)/1000.0 != test_values[value][j]:
                            print value, ": failed"
                            return 1
        print value, ": ok"
    print "OK (All %d tests)" %len(values)

if __name__ == "__main__":
    _test()

    # import sys
    # from werkzeug.serving import run_simple

    # from pydap.wsgi.ssf import ServerSideFunctions
    # application = ServerSideFunctions(application)
    # run_simple('localhost', 8001, application, use_reloader=True)