#!/usr/bin/env python3

import os
import unittest

import yaml
import amulet


class TestBundle(unittest.TestCase):
    bundle_file = os.path.join(os.path.dirname(__file__), '..', 'bundle.yaml')

    @classmethod
    def setUpClass(cls):
        cls.d = amulet.Deployment(series='trusty')
        with open(cls.bundle_file) as f:
            bun = f.read()
        bundle = yaml.safe_load(bun)
        cls.d.load(bundle)
        cls.d.setup(timeout=1800)
        cls.d.sentry.wait_for_messages({'hive': 'Ready'}, timeout=1800)
        cls.hdfs = cls.d.sentry['namenode'][0]
        cls.yarn = cls.d.sentry['resourcemanager'][0]
        cls.slave = cls.d.sentry['slave'][0]
        cls.hive = cls.d.sentry['hive'][0]

    def test_components(self):
        """
        Confirm that all of the required components are up and running.
        """
        hdfs, retcode = self.hdfs.run("pgrep -a java")
        yarn, retcode = self.yarn.run("pgrep -a java")
        slave, retcode = self.slave.run("pgrep -a java")
        hive, retcode = self.hive.run("pgrep -a java")

        # .NameNode needs the . to differentiate it from SecondaryNameNode
        assert '.NameNode' in hdfs, "NameNode not started"
        assert '.NameNode' not in yarn, "NameNode should not be running on resourcemanager"
        assert '.NameNode' not in slave, "NameNode should not be running on slave"
        assert '.NameNode' not in hive, "NameNode should not be running on hive"

        assert 'ResourceManager' in yarn, "ResourceManager not started"
        assert 'ResourceManager' not in hdfs, "ResourceManager should not be running on namenode"
        assert 'ResourceManager' not in slave, "ResourceManager should not be running on slave"
        assert 'ResourceManager' not in hive, "ResourceManager should not be running on hive"

        assert 'JobHistoryServer' in yarn, "JobHistoryServer not started"
        assert 'JobHistoryServer' not in hdfs, "JobHistoryServer should not be running on namenode"
        assert 'JobHistoryServer' not in slave, "JobHistoryServer should not be running on slave"
        assert 'JobHistoryServer' not in hive, "JobHistoryServer should not be running on hive"

        assert 'NodeManager' in slave, "NodeManager not started"
        assert 'NodeManager' not in yarn, "NodeManager should not be running on resourcemanager"
        assert 'NodeManager' not in hdfs, "NodeManager should not be running on namenode"
        assert 'NodeManager' not in hive, "NodeManager should not be running on hive"

        assert 'DataNode' in slave, "DataServer not started"
        assert 'DataNode' not in yarn, "DataNode should not be running on resourcemanager"
        assert 'DataNode' not in hdfs, "DataNode should not be running on namenode"
        assert 'DataNode' not in hive, "DataNode should not be running on hive"

        assert 'HiveServer2' in hive, 'Hive should be running on hive'

    def test_hdfs_dir(self):
        """
        Validate admin few hadoop activities on HDFS cluster.
            1) This test validates mkdir on hdfs cluster
            2) This test validates change hdfs dir owner on the cluster
            3) This test validates setting hdfs directory access permission on the cluster

        NB: These are order-dependent, so must be done as part of a single test case.
        """
        output, retcode = self.hive.run("su hdfs -c 'hdfs dfs -mkdir -p /user/ubuntu'")
        assert retcode == 0, "Created a user directory on hdfs FAILED:\n{}".format(output)
        output, retcode = self.hive.run("su hdfs -c 'hdfs dfs -chown ubuntu:ubuntu /user/ubuntu'")
        assert retcode == 0, "Assigning an owner to hdfs directory FAILED:\n{}".format(output)
        output, retcode = self.hive.run("su hdfs -c 'hdfs dfs -chmod -R 755 /user/ubuntu'")
        assert retcode == 0, "seting directory permission on hdfs FAILED:\n{}".format(output)

    def test_yarn_mapreduce_exe(self):
        """
        Validate yarn mapreduce operations:
            1) validate mapreduce execution - writing to hdfs
            2) validate successful mapreduce operation after the execution
            3) validate mapreduce execution - reading and writing to hdfs
            4) validate successful mapreduce operation after the execution
            5) validate successful deletion of mapreduce operation result from hdfs

        NB: These are order-dependent, so must be done as part of a single test case.
        """
        jar_file = '/usr/lib/hadoop/share/hadoop/mapreduce/hadoop-mapreduce-examples-*.jar'
        test_steps = [
            ('teragen',      "su ubuntu -c 'hadoop jar {} teragen  10000 /user/ubuntu/teragenout'".format(jar_file)),
            ('mapreduce #1', "su hdfs -c 'hdfs dfs -ls /user/ubuntu/teragenout/_SUCCESS'"),
            ('terasort',     "su ubuntu -c 'hadoop jar {} terasort /user/ubuntu/teragenout /user/ubuntu/terasortout'".
                format(jar_file)),
            ('mapreduce #2', "su hdfs -c 'hdfs dfs -ls /user/ubuntu/terasortout/_SUCCESS'"),
            ('cleanup #1',   "su hdfs -c 'hdfs dfs -rm -r /user/ubuntu/teragenout'"),
            ('cleanup #2',   "su hdfs -c 'hdfs dfs -rm -r /user/ubuntu/terasortout'"),
        ]
        for name, step in test_steps:
            output, retcode = self.hive.run(step)
            assert retcode == 0, "{} FAILED:\n{}".format(name, output)

    def _run_sql(self, cmd, sql):
        output, retcode = self.hive.run((
            "echo '{sql}' > test.sql; "
            "sudo su hive -c '{cmd} -f test.sql 2>&1'"
        ).format(cmd=cmd, sql=sql))
        assert retcode == 0, 'Hive command failed (%s): %s' % (retcode, output)
        return output

    def test_hive(self):
        output = self._run_sql('hive', 'show tables;')
        self.assertNotIn('test_cli', output)

        output = self._run_sql(
            'hive',
            'create table test_cli(col1 int, col2 string); '
            'show tables;')
        self.assertIn('test_cli', output)
        self._run_sql('hive', 'drop table test_cli;')

    def test_beeline(self):
        output = self._run_sql(
            'beeline',
            '!connect jdbc:hive2://localhost:10000 hive password'
            ' org.apache.hive.jdbc.HiveDriver;'
            'show tables;')
        self.assertNotIn('test_beeline', output)

        output = self._run_sql(
            'beeline',
            '!connect jdbc:hive2://localhost:10000 hive password'
            ' org.apache.hive.jdbc.HiveDriver;'
            'create table test_beeline(col1 int, col2 string); '
            'show tables;')
        self.assertIn('test_beeline', output)
        self._run_sql(
            'beeline',
            '!connect jdbc:hive2://localhost:10000 hive password'
            ' org.apache.hive.jdbc.HiveDriver;'
            'drop table test_beeline;')


if __name__ == '__main__':
    unittest.main()
