import os

MAX_LOG_FILE_SIZE = 128*1024*1024

class TraceLogging:
    def __init__(self, log_file_name):
        self.log_file_name = log_file_name

    def check_to_truncate_file(self):
        if os.path.exists(self.log_file_name):
            st = os.stat(self.log_file_name)
            if st.st_size > MAX_LOG_FILE_SIZE:
                file_name = os.path.basename(self.log_file_name)
                location = os.path.dirname(self.log_file_name)
                rename_to = location + "/" + "old_" + file_name
                os.rename(self.log_file_name, rename_to)

    def log_msg(self, log_msg):
        self.check_to_truncate_file()
        print (log_msg)
        with open(self.log_file_name, "a") as log_fd:
            log_fd.write(log_msg)
            log_fd.write("\n")
