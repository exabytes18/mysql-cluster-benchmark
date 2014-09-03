# http://boto.readthedocs.org/en/latest/ref/ec2.html
import boto.ec2
import boto.vpc
import boto.exception
import re
import time

# http://docs.fabfile.org/en/latest/api/core/operations.html
from fabric.api import abort, env, puts, run, sudo
from fabric.decorators import runs_once, task


@task
@runs_once
def create_placement_group(name=None):
    if name is None:
        abort('\n'
              '\n'
              '    You must specify a name for the placement group:\n'
              '        fab create_placement_group:NAME\n')

    ec2 = boto.ec2.connect_to_region(env.ec2_region)
    try:
        if ec2.create_placement_group(name):
            puts('\n'
                 '    "%s" placement group created successfully!' % name)
        else:
            abort('\n'
                  '\n'
                  '    "%s" placement group could not be created!' % name)
    except boto.exception.EC2ResponseError as e:
        if e.error_code == 'InvalidPlacementGroup.Duplicate':
            puts('\n'
                 '    "%s" placement group already exists' % name)
        else:
            abort('\n'
                  '\n'
                  '    "%s" placement group could not be created!: %s' %
                  (name, e.message))


@task
@runs_once
def allow_source_traffic(sg=None, src=None):
    if sg is None or src is None:
        abort('\n'
              '\n'
              '    You must specify the id of a security group as well as the id of the:\n'
              '    source security group:\n'
              '        fab allow_source_traffic:sg=sg-xxxxxx,src=sg-yyyyyyyy\n')

    ec2 = boto.ec2.connect_to_region(env.ec2_region)
    ec2.authorize_security_group(
        group_id=sg,
        ip_protocol=-1,
        from_port=0,
        to_port=65535,
        src_security_group_group_id=src)

    puts('\n'
         '    "%s" security group updated successfully!' % sg)


@task
@runs_once
def create_vpn_security_group(name=None):
    if name is None:
        abort('\n'
              '\n'
              '    You must specify a name for the security group:\n'
              '        fab create_vpn_security_group:NAME\n')

    _create_security_group_abort_on_error(
        name=name,
        desc='%s security group' % name,
        rules=[
            ('tcp', 22, 22, '0.0.0.0/0'),
            ('udp', 500, 500, '0.0.0.0/0'),
            ('udp', 4500, 4500, '0.0.0.0/0'),
        ])


@task
@runs_once
def create_open_security_group(name=None):
    if name is None:
        abort('\n'
              '\n'
              '    You must specify a name for the security group:\n'
              '        fab create_open_security_group:NAME\n')

    _create_security_group_abort_on_error(
        name=name,
        desc='%s security group' % name,
        rules=[(-1, 0, 65535, '0.0.0.0/0')])


def _create_security_group_abort_on_error(name, desc, rules):
    ec2 = boto.ec2.connect_to_region(env.ec2_region)
    try:
        sg = ec2.create_security_group(name, desc, vpc_id=env.ec2_vpc_id)
    except boto.exception.EC2ResponseError as e:
        if e.error_code == 'InvalidGroup.Duplicate':
            abort('\n'
                  '\n'
                  '    "%s" security group already exists!' % name)
        else:
            abort('\n'
                  '\n'
                  '    "%s" security group could not be created!: %s' %
                  (name, e.message))

    for rule in rules:
        ec2.authorize_security_group(
            group_id=sg.id,
            ip_protocol=rule[0],
            from_port=rule[1],
            to_port=rule[2],
            cidr_ip=rule[3])

    puts('\n'
         '    "%s" security group created successfully!' % name)


@task
@runs_once
def launch_instances(group=None):
    vpc = boto.vpc.connect_to_region(env.ec2_region)
    if group is None:
        error_message = ('\n'
                         '\n'
                         '    Please specify a group:\n'
                         '        fab launch_instances:group=xxxx\n'
                         '\n')

        error_message += '    Groups:\n'
        for group in env.ec2_instances.keys():
            error_message += '        %s\n' % group

        abort(error_message)


    if group not in env.ec2_instances:
        abort('\n'
              '\n'
              '    Unknown group "%s"' % group)
    config = env.ec2_instances[group]

    security_group_ids = []
    security_groups = config.get('security_groups', [])
    if security_groups is not None:
        for security_group in security_groups:
            security_group_ids.append(
                _get_security_group_id_abort_on_error(security_group))

    if 'roles' in config:
        tags = {}
        for role in config['roles']:
            tags['mysql-cluster-benchmark-%s' % role] = '1'
    else:
        tags = None

    _launch_instances_abort_on_error(
        ami=config['ami'],
        bid=config['bid'],
        count=config.get('count', 1),
        instance_type=config['type'],
        subnet=config['subnet'],
        assign_public_ip=config.get('assign_public_ip', False),
        source_dest_check=config.get('source_dest_check', True),
        placement_group=config.get('placement_group'),
        disks=config.get('ephemeral_disks', None),
        security_group_ids=security_group_ids,
        tags=tags)


def _launch_instances_abort_on_error(ami,
                                     bid,
                                     count,
                                     instance_type,
                                     subnet,
                                     assign_public_ip,
                                     source_dest_check,
                                     placement_group,
                                     disks,
                                     security_group_ids,
                                     tags=None):
    ephemeral_idx = 0
    bdm = boto.ec2.blockdevicemapping.BlockDeviceMapping()
    if disks is not None:
        for disk in disks:
            bdm[disk] = boto.ec2.blockdevicemapping.BlockDeviceType(
                ephemeral_name='ephemeral%d' % ephemeral_idx)
            ephemeral_idx += 1

    nics = boto.ec2.networkinterface.NetworkInterfaceCollection()
    nics.append(boto.ec2.networkinterface.NetworkInterfaceSpecification(
        subnet_id=subnet,
        groups=security_group_ids,
        associate_public_ip_address=assign_public_ip))

    ec2 = boto.ec2.connect_to_region(env.ec2_region)
    sirs = ec2.request_spot_instances(
        price=bid,
        image_id=ami,
        count=count,
        type='one-time',
        key_name=env.ec2_key_pair_name,
        instance_type=instance_type,
        monitoring_enabled=True,
        placement_group=placement_group,
        block_device_map=bdm,
        network_interfaces=nics)

    instance_ids = set()
    while True:
        time.sleep(10)
        done = True
        for sir in ec2.get_all_spot_instance_requests(map(lambda x: x.id, sirs)):
            print 'State:  %s' % sir.state
            print 'Fault:  %s' % sir.fault
            print 'Status: %s' % sir.status.message
            if sir.state not in ('open', 'active'):
                abort('Failed to launch instances')
            if sir.state == 'open':
                done = False
            if sir.state == 'active':
                instance_ids.add(sir.instance_id)

        if done:
            break

    for instance_id in instance_ids:
        ec2.modify_instance_attribute(
            instance_id=instance_id,
            attribute='sourceDestCheck',
            value=source_dest_check)

    print ''
    print 'Instances:'
    for reservation in ec2.get_all_instances(list(instance_ids)):
        for instance in reservation.instances:
            if tags is not None:
                instance.add_tags(tags)

            print '    %s' % instance.id
            print '        type:        %s' % instance.instance_type
            print '        internal ip: %s' % instance.private_ip_address
            print '        public ip:   %s' % instance.ip_address
            print '        tags:'
            for tag, value in sorted(instance.tags.iteritems(), lambda a, b: cmp(a[0], b[0])):
                print '            %s: %s' % (tag, value)


def _get_security_group_id_abort_on_error(name):
    ec2 = boto.ec2.connect_to_region(env.ec2_region)
    for security_group in ec2.get_all_security_groups():
        if security_group.name == name and \
                security_group.vpc_id == env.ec2_vpc_id:
            return security_group.id
    abort('Unable to get id for "%s" security group. '
          'Did you create it yet?' % name)


@task
@runs_once
def list_instances():
    instances = {}
    ec2 = boto.ec2.connect_to_region(env.ec2_region)
    for reservation in ec2.get_all_reservations():
        for instance in reservation.instances:
            if instance.vpc_id == env.ec2_vpc_id:
                (instances.setdefault(instance.placement_group, [])
                          .append(instance))
    print ''
    for pg, instances in instances.iteritems():
        for instance in instances:
            print '    %s (%s):    %s' % (instance.id,
                                          instance.instance_type,
                                          instance.private_ip_address)


def get_instances_callable(role=None, mapper=None):
    def fn():
        filters = {}
        if role is not None:
            filters['tag:mysql-cluster-benchmark-%s' % role] = '1'

        instances = []
        ec2 = boto.ec2.connect_to_region(env.ec2_region)
        for reservation in ec2.get_all_instances(filters=filters):
            for instance in reservation.instances:
                if instance.state != 'terminated':
                    instances.append(instance)
        return instances if mapper is None else map(mapper, instances)

    return fn


def get_instance_by_ip(ip):
    ec2 = boto.ec2.connect_to_region(env.ec2_region)
    for reservation in ec2.get_all_instances():
        for instance in reservation.instances:
            if instance.state != 'terminated' and \
                    (instance.ip_address == ip or \
                        instance.private_ip_address == ip):
                return instance
    return None



@task
@runs_once
def spot_prices():
    ec2 = boto.ec2.connect_to_region(env.ec2_region)
    pricing = ec2.get_spot_price_history(
        product_description='Linux/UNIX (Amazon VPC)')

    type_az_sph = {}
    for sph in pricing:
        type_az = type_az_sph.setdefault(sph.instance_type, {})
        if sph.availability_zone not in type_az or \
                sph.availability_zone > type_az[sph.availability_zone].timestamp:
            type_az[sph.availability_zone] = sph

    def _inst_cmp(a, b):
        a_cls, a_dot, a_size = a[0].partition('.')
        b_cls, b_dot, b_size = b[0].partition('.')

        a_cat, a_gen = (a_cls[0], int(a_cls[1]))
        b_cat, b_gen = (b_cls[0], int(b_cls[1]))

        a_parsed_size = re.match(r'(\d*)(.+)', a_size)
        b_parsed_size = re.match(r'(\d*)(.+)', b_size)

        ranks = ['micro', 'small', 'medium', 'large', 'xlarge']
        a_rank = ranks.index(a_parsed_size.group(2))
        b_rank = ranks.index(b_parsed_size.group(2))
        a_sub_rank = int(a_parsed_size.group(1) or 0)
        b_sub_rank = int(b_parsed_size.group(1) or 0)

        if a_cat < b_cat:
            return -1
        elif a_cat > b_cat:
            return 1
        elif a_gen < b_gen:
            return -1
        elif a_gen > b_gen:
            return 1
        elif a_rank < b_rank:
            return -1
        elif a_rank > b_rank:
            return 1
        elif a_sub_rank < b_sub_rank:
            return -1
        elif a_sub_rank > b_sub_rank:
            return 1
        else:
            return 0

    last_inst_cls = None
    print ''
    for instance_type, az_sph in sorted(type_az_sph.iteritems(), _inst_cmp):
        inst_cls = instance_type.partition('.')[0]
        if last_inst_cls != inst_cls and last_inst_cls is not None:
            print '    ' + '-' * 25

        print '    %s' % instance_type
        for az, sph in sorted(az_sph.iteritems(), lambda a, b: cmp(a[0], b[0])):
            print '        %s: %f' % (az, sph.price)

        last_inst_cls = inst_cls
