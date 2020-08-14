from troposphere import ec2, efs
from troposphere import Join, Output, Ref, GetAtt

from stacker.blueprints.base import Blueprint
from stacker.blueprints.variables.types import TroposphereType
from stacker.exceptions import ValidatorError

from stacker_blueprints.util import merge_tags


class ElasticFileSystem(Blueprint):
    VARIABLES = {
        'FileSystem': {
            'type': TroposphereType(efs.FileSystem),
            'description': 'A dictionary of the FileSystem to create. The key '
                           'being the CFN logical resource name, the '
                           'value being a dictionary of attributes for '
                           'the troposphere efs.FileSystem type.',
        },
        'VpcId': {
            'type': str,
            'description': 'VPC ID to create resources'
        },
        'Tags': {
            'type': dict,
            'description': 'Tags to associate with the created resources',
            'default': {}
        },
        'Subnets': {
            'type': list,
            'description': 'List of subnets to deploy private mount targets '
                           'in. Can not be used together with SubnetsStr. You'
                           'must choose only one way to inform this parameter',

            'default': []
        },
        'SubnetsStr': {
            'type': str,
            'description': 'A comma sepparated list of subnets to deploy '
                           'private mount targets in. Can not be used in '
                           'addition to Subnets, you must choose only one way'
                           'to inform this parameter',
            'default': ''
        },
        'IpAddresses': {
            'type': list,
            'description': 'List of IP addresses to assign to mount targets. '
                           'Omit or make empty to assign automatically. '
                           'Corresponds to Subnets listed in the same order.',
            'default': []
        },
        'SecurityGroups': {
            'type': TroposphereType(ec2.SecurityGroup, many=True,
                                    optional=True, validate=False),
            'description': "Dictionary of titles to SecurityGroups "
                           "definitions to be created and assigned to this "
                           "filesystem's MountTargets. "
                           "The VpcId property will be filled automatically, "
                           "so it should not be included. \n"
                           "The IDs of the created groups will be exported as "
                           "a comma-separated list in the "
                           "EfsNewSecurityGroupIds output.\n"
                           "Omit this parameter or set it to an empty "
                           "dictionary to not create any groups. In that "
                           "case the ExistingSecurityGroups variable must not "
                           "be empty",
            'default': {}
        },
        'ExtraSecurityGroups': {
            'type': list,
            'description': "List of existing SecurityGroup IDs to be asigned "
                           "to this filesystem's MountTargets",
            'default': []
        }
    }

    def get_subnets_from_string_list(self):
        v = self.get_variables()

        def check_empty_string(value):
            return value != ''

        subnets = v['SubnetsStr'].split(',')
        return filter(check_empty_string, subnets)

    def validate_efs_security_groups(self):
        validator = '{}.{}'.format(type(self).__name__,
                                   'validate_efs_security_groups')
        v = self.get_variables()
        count = len(v['SecurityGroups'] or []) + len(v['ExtraSecurityGroups'])

        if count == 0:
            raise ValidatorError(
                'SecurityGroups,ExtraSecurityGroups', validator, count,
                'At least one SecurityGroup must be provided')
        elif count > 5:
            raise ValidatorError(
                'SecurityGroups,ExtraSecurityGroups', validator, count,
                'At most five total SecurityGroups must be provided')

    def validate_efs_subnets(self):
        validator = '{}.{}'.format(type(self).__name__, 'validate_efs_subnets')
        v = self.get_variables()

        subnet_count = len(v['Subnets'])
        subnet_str_count = len(self.get_subnets_from_string_list())
        if not subnet_count and not subnet_str_count:
            variables = {
                'Subnets': v['Subnets'],
                'SubnetsStr': v['SubnetsStr']
            }
            raise ValidatorError(
                'Subnets', validator,  variables,
                'At least one Subnet or SubnetStr must be provided')

        if subnet_count and subnet_str_count:
            variables = {
                'Subnets': v['Subnets'],
                'SubnetsStr': v['SubnetsStr']
            }
            raise ValidatorError(
                'Subnets and SubnetsStr', validator,  variables,
                'Only one of Subnet or SubnetStr can be provided')

        ip_count = len(v['IpAddresses'])
        if ip_count and ip_count != max(subnet_count, subnet_str_count):
            raise ValidatorError(
                'IpAddresses', validator, v['IpAddresses'],
                'The number of IpAddresses must match the number of Subnets')

    def resolve_variables(self, provided_variables):
        super(ElasticFileSystem, self).resolve_variables(provided_variables)

        self.validate_efs_security_groups()
        self.validate_efs_subnets()

    def prepare_efs_security_groups(self):
        t = self.template
        v = self.get_variables()

        created_groups = []
        for sg in v['SecurityGroups'] or {}:
            sg.VpcId = v['VpcId']
            sg.Tags = merge_tags(v['Tags'], getattr(sg, 'Tags', {}))

            sg = t.add_resource(sg)
            created_groups.append(sg)

        created_group_ids = list(map(Ref, created_groups))
        t.add_output(Output(
            'EfsNewSecurityGroupIds',
            Value=Join(',', created_group_ids)))

        groups_ids = created_group_ids + v['ExtraSecurityGroups']
        return groups_ids

    def create_efs_filesystem(self):
        t = self.template
        v = self.get_variables()

        fs = v.get('FileSystem')

        # This is a major hack to inject extra tags in efs resources
        fs.FileSystemTags = merge_tags(v['Tags'], getattr(fs, 'Tags', {}))

        fs = t.add_resource(fs)
        t.add_output(Output(
            'EfsFileSystemId',
            Value=Ref(fs)))

        return fs

    def create_efs_mount_targets(self, fs):
        t = self.template
        v = self.get_variables()

        groups = self.prepare_efs_security_groups()

        subnets = self.get_subnets_from_string_list()
        subnets += v['Subnets']
        ips = v['IpAddresses']

        mount_targets = []
        for i, subnet in enumerate(subnets):
            mount_target = efs.MountTarget(
                'EfsMountTarget{}'.format(i + 1),
                FileSystemId=Ref(fs),
                SubnetId=subnet,
                SecurityGroups=groups)

            if ips:
                mount_target.IpAddress = ips[i]

            mount_target = t.add_resource(mount_target)
            mount_targets.append(mount_target)

        t.add_output(Output(
            'EfsMountTargetIds',
            Value=Join(',', list(map(Ref, mount_targets)))))

    def create_template(self):
        fs = self.create_efs_filesystem()
        self.create_efs_mount_targets(fs)


class AccessPoints(Blueprint):
    VARIABLES = {
        'AccessPoints': {
            'type': TroposphereType(efs.AccessPoint, many=True),
            'description': 'A dictionary of the AccessPoints to create. The '
                           'key being the CFN logical resource name, the '
                           'value being a dictionary of attributes for '
                           'the troposphere efs.FileSystem type.',
        },
        'Tags': {
            'type': dict,
            'description': 'Tags to associate with the created resources',
            'default': {}
        }
    }

    def create_template(self):
        t = self.template
        v = self.get_variables()

        access_points = v.get('AccessPoints')
        tags = v.get('Tags')

        for ap in access_points:
            # This is a major hack to inject extra tags in resources
            ap.AccessPointTags = merge_tags(tags, getattr(ap, 'Tags', {}))
            ap_name = ap.name
            ap = t.add_resource(ap)
            t.add_output(Output(
                '{}Id'.format(ap_name),
                Value=GetAtt(ap, 'AccessPointId')))
            t.add_output(Output(
                '{}Arn'.format(ap_name),
                Value=GetAtt(ap, 'Arn')))
