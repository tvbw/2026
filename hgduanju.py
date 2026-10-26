from base.spider import Spider as BaseSpider

class Spider(BaseSpider):
    def getName(self):
        return "红果短剧"

    def init(self, extend=""):
        pass

    def homeContent(self, filter):
        return {
            "class": [{"type_id": "test", "type_name": "测试目录"}],
            "list": []
        }

    def homeVideoContent(self):
        return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        return {"list": []}

    def searchContent(self, key, quick=False, pg="1"):
        return {"list": []}

    def detailContent(self, ids):
        return {"list": []}

    def playerContent(self, flag, id, vipFlags=None):
        return {"parse": 1, "url": ""}

if __name__ == '__main__':
    BaseSpider.register(Spider())
